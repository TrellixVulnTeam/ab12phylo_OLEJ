# 2020 Leo Kaindl

"""
The command line interface of the package defines possible options and parses valid arguments
from user input via `sys.argv`, supplemented by the `config/config.yaml` file.
Arguments will be saved as an :class:`argparse.Namespace` object and directly accessed by the
:class:`main` module. Additionally, this module initiates logging.
"""

import os
import sys
import yaml
import random
import logging
import argparse

from os import path
from ab12phylo import main, phylo


class parser(argparse.ArgumentParser):
    """
    The command line parser of the package.
    Run `ab12phylo -h` to display all available options.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(prog='ab12phylo')

        # if empty commandline show help
        args = args if len(args[0]) > 0 else (['-h'],) + args[1:]

        ion = parser.add_argument_group(self, title='FILE I/O')
        ion.add_argument('-abi', '--abi_dir',
                         help='Root directory of ABI trace files. Defaults to test data set.',
                         type=lambda arg: arg if path.isdir(arg) else self.error(
                             '%s: invalid ABI trace file directory' % arg))

        ion.add_argument('-abiset', '--abi_set',
                         help='Whitelist file defining subset of ABI traces for the analysis.'
                              'Files must be in or below provided \'--abi_dir\' directory.',
                         type=lambda arg: arg if path.isfile(arg) else self.error(
                             '%s: invalid whitelist file' % arg))

        ion.add_argument('-sampleset', '--sample_set',
                         help='Whitelist file defining subset of sample IDs for the analysis.'
                              'Different versions of a sample will be included.',
                         type=lambda arg: arg if path.isfile(arg) else self.error(
                             '%s: invalid sample whitelist' % arg))

        ion.add_argument('-csv', '--csv_dir',
                         help='Root directory of .csv files with well-to-isolate coordinates. '
                              'Defaults to test data set',
                         type=lambda arg: arg if path.isdir(arg) else self.error(
                             '%s: invalid directory of well-to-isolate coordinate .csv files' % arg))

        ion.add_argument('-dir', '--dir',
                         help='Directory that output files will be created in. Defaults to \'./results\'')

        ion.add_argument('-g', '--genes', nargs='+',
                         help='Gene(s) to be considered; first argument defines gene for species annotation. '
                              'If set, only ABI traces with a filename matching one of these patterns will be read.')

        refs = ion.add_mutually_exclusive_group()
        refs.add_argument('-rf', '--ref', nargs='+',
                          help='Optional paths of .fasta-formatted files containing reference sequences. '
                               'Files will be matched to genes by order if --genes is set, otherwise by filename.',
                          type=lambda arg: arg if path.isfile(arg) else self.error(
                              'invalid file path(s) with .fasta-formatted reference sequences:\n%s' % arg))

        refs.add_argument('-rd', '--ref_dir', type=self._valid_ref_dir,
                          help='Directory of .fasta files with reference sequences. Files will be matched to genes '
                               'by their filename. Provide at most one option from {--ref, --ref_dir}.')

        # [quality]
        qal = parser.add_argument_group(self, title='QUALITY')
        qal.add_argument('-qal', '--min_phred', type=int,
                         help='Minimal phred quality score to define \'good\' bases in ABI trace files. '
                              'Default minimal score is 30.')

        qal.add_argument('-bad', '--bad_stretch', type=int,
                         help='Number of consecutive \'bad bases\': Any sequence of bases in an ABI trace file '
                              'with a phred quality score below the minimum and at least as long as the number '
                              'supplied here will be replaced by a sequence of Ns of equal length.')

        qal.add_argument('-end', '--end_ratio', type=self._valid_end_ratio,
                         help='Defines a \'good end\' of a sequence in an ABI trace file for trimming. '
                              'Enter as "<int>/<int>".')

        # [BLAST]
        bla = parser.add_argument_group(self, title='BLAST')
        skips = bla.add_mutually_exclusive_group()
        skips.add_argument('-skip', '--no_remote', action='store_true',
                           help='NCBI BLAST API queries are de-prioritized very quickly. Set this flag to skip online '
                                'nucleotide BLAST for seqs missing from the local database.')
        skips.add_argument('-none', '--no_BLAST', action='store_true',
                           help='Skip BLAST entirely.')

        bla.add_argument('-db', '--db', help='Selected BLAST+ database name, mostly untested.')

        bla.add_argument('-dbpath', '--dbpath',
                         help='Optional path to directory with BLAST+ database. Set if tool is not allowed FTP access.',
                         type=lambda arg: arg if path.isdir(arg) else self.error(
                             'invalid path to directory containing BLAST database'))

        # [MSA]
        msa = parser.add_argument_group(self, title='MSA')
        msa.add_argument('-algo', '--msa_algo', choices=['clustalo', 'mafft', 'muscle', 't_coffee'],
                         help='Select an algorithm to build the Multiple Sequence Alignment. Default is MAFFT.')

        msa.add_argument('-gbl', '--gblocks', choices=['skip', 'relaxed', 'strict'],
                         help='Activate/set MSA trimming with Gblocks.')

        # [raxml]
        phy = parser.add_argument_group(self, title='RAxML-NG')
        phy.add_argument('-st', '--start_trees', type=self._valid_start_trees,
                         help='Numbers of starting trees for raxml-ng tree inference: '
                              '[<int random trees>,<int parsimony-based trees>].')

        phy.add_argument('-bst', '--bootstrap', type=self._valid_bootstrap,
                         help='Maximum number of bootstrap trees for raxml-ng.')

        phy.add_argument('-metric', '--metric', choices=['TBE', 'FBP'],
                         help='Bootstrap support metric: Either Felsenstein Bootstrap Proportions (FBP) '
                              'or Transfer Bootstrap Expectation(TBE).')

        phy.add_argument('-s', '--seed', type=int,
                         help='Seed value for reproducible tree inference results. Will be random if not set.')

        # [config]
        self.add_argument('-config', '--config',
                          default=path.abspath(path.join(path.dirname(__file__), 'config', 'config.yaml')),
                          type=lambda arg: arg if path.isfile(arg) else self.error('%s: invalid .config path'),
                          help='Path to .yaml config file with defaults. Command line arguments will override.')

        # [misc]
        self.add_argument('-v', '--verbose', action='store_true', help='Show more information in console output.')
        self.add_argument('-version', '--version', action='store_true', help='Print version information and exit.')
        self.add_argument('-test', '--test', action='store_true', help='Test run.')
        self.add_argument('-msa_viz', '--msa_viz', action='store_true',
                          help='Also render a rectangular tree with MSA. Takes quite some extra time.')
        self.add_argument('-viz', '--visualize', action='store_true',
                          help='Invoke ab12phylo-visualize by appending ab12phylo cmd.')
        self.add_argument('-view', '--view', action='store_true',
                          help='Invoke ab12phylo-view by appending ab12phylo cmd.')
        self.add_argument('-q', '--headless', action='store_true',
                          help='Prevents starting of a CGI server and display in browser. For remote use.')

        # [ab12phylo-visualize]
        vie = parser.add_argument_group(self, title='ONLY FOR AB12PHYLO-VISUALIZE')
        vie.add_argument('result_dir', nargs='?', help='Path to results of earlier run.')

        self.args = self.parse_args(args[0])

        if self.args.version is True:
            sys.exit('ab12phylo: %s' % main.__version__)

        # test: switch config + set verbose
        if self.args.test is True:
            print('--TEST RUN--', file=sys.stderr)
            self.args.config = path.abspath(path.join(path.dirname(__file__), 'config', 'test_config.yaml'))
            self.args.verbose = True

        # load additional info from config
        assert self.args.config is not None
        config = yaml.safe_load(open(self.args.config, 'r'))

        # if refs were set manually; and genes as well, or there is only 1 reference -> match refs to genes by order
        by_order = True if self.args.ref is not None \
                           and (self.args.genes is not None or len(self.args.ref) == 1) else False

        config_only = dict()
        # provide defaults for unset options
        for key, val in config.items():
            if key not in self.args:
                # for itemw without CLI equivalent (avoid bloated CLI)
                config_only[key] = val
            elif self.args.__dict__.get(key) in [None, False]:
                # access the namespace itself without var names -> access dict
                if key in ['abi_dir', 'csv_dir', 'blastdb', 'abi_set', 'sample_set', 'dir'] and val[0] == '$':
                    # deal with relative paths in config for test case
                    val = path.join(path.dirname(path.dirname(__file__)), val[1:])
                if key == 'ref':
                    # split into list
                    val = [ref.strip() for ref in val.split(',')]
                    # make absolute paths
                    val = [path.join(path.dirname(path.dirname(__file__)), ref[1:])
                           if ref[0] == '$' else ref for ref in val]

                self.args.__dict__[key] = val

        # ab12phylo with --visualize or --view: guess real results path and skip re-parsing
        if len(kwargs) > 0 or self.args.visualize or self.args.view:
            print('--VISUALIZE/VIEW--', file=sys.stderr)

            # look in current working directory and ./results
            found = False
            for outer in [self.args.result_dir, self.args.dir, os.getcwd()]:
                if found:
                    break
                if outer is None:
                    continue
                elif outer == '.':
                    outer = os.getcwd()
                for inner in ['', 'results']:
                    if path.isfile(path.join(outer, inner, 'tree_TBE.nwk')):
                        # MARK filename is hardcoded manually from below.
                        self.args.dir = path.join(outer, inner)
                        found = True
                        break
            if not found:
                sys.exit('Result files not found')

        else:  # normal case

            # move ref file list from ref_dir to ref
            if self.args.ref_dir:
                self.args.ref = self.args.ref_dir
                del self.args.ref_dir

            # check for duplicates in genes and references
            if self.args.genes is not None:
                if len(set(self.args.genes)) < len(self.args.genes):
                    self.error('duplicates in supplied genes')
            if self.args.ref is not None and len(set(self.args.ref)) < len(list(self.args.ref)):
                self.error('duplicates in supplied references')

            # now rebuild a command line and parse it again
            commandline = list()
            for key, val in self.args.__dict__.items():
                if key in ['genes', 'ref'] and val is not None:
                    commandline.append('--%s' % key)
                    [commandline.append(gene) for gene in val]
                elif val not in [None, False, True]:
                    commandline += ['--%s' % key, str(val)]
                elif val is True:
                    commandline.append('--%s' % key)

            self.args = self.parse_args(commandline)

            # remember type of original ref option
            self.args.by_order = by_order

            # create output directory already
            if self.args.dir is not None:
                os.makedirs(self.args.dir, exist_ok=True)
            else:
                # write results to current directory.
                self.args.dir = ''

            # define a random seed if None was given
            if self.args.seed is None:
                self.args.seed = random.randint(0, 1000)

        # set some default values where options would be useless
        self.args.xml = path.join(self.args.dir, 'local_blast+_result.xml')
        self.args.www_xml = path.join(self.args.dir, 'online_blast_result.xml')
        self.args.bad_seqs = path.join(self.args.dir, 'bad_seqs.tsv')
        self.args.missing_samples = path.join(self.args.dir, 'missing_samples.tsv')
        self.args.tsv = path.join(self.args.dir, 'metadata.tsv')
        self.args.msa = path.join(self.args.dir, 'msa.fasta')
        self.args.new_msa = path.join(self.args.dir, 'msa_annotated.fasta')
        self.args.mview_msa = path.join(self.args.dir, 'msa_mview.html')
        self.args.topo = path.join(self.args.dir, 'topology_preview.png')
        self.args.missing_fasta = path.join(self.args.dir, 'missing.fasta')
        self.args.final_tree = path.join(self.args.dir, 'tree')
        self.args.annotated_tree = path.join(self.args.dir, 'tree_%s_annotated.nwk' % self.args.metric)
        self.args.log = path.join(self.args.dir, 'ab12phylo.log')
        self.args.sep = 'SSSSSSSSSS'  # to visually separate genes in the concat MSA
        # now also load config-only defaults
        self.args.__dict__.update(config_only)

        # switching to visualize and view
        if self.args.visualize:
            self._init_log(self.args.log[:-4] + '-viz.log')
            log = logging.getLogger(__name__)
            log.debug('--AB12PHYLO-VISUALIZE--')
            log.debug(' '.join(args[0]))
            phylo.tree_build(self.args)
            sys.exit(0)

        if self.args.view:
            self.args.headless = False
            self._init_log(self.args.log[:-4] + '-view.log')
            log = logging.getLogger(__name__)
            log.debug('--AB12PHYLO-VIEW--')
            log.debug(' '.join(args[0]))
            phylo.tree_view(self.args.dir)
            sys.exit(0)

        # configure logging:
        if len(kwargs) > 0:
            self._init_log(self.args.log[:-4] + '-view-viz.log')
            log = logging.getLogger(__name__)
            log.debug(' '.join(args[0]))
        else:
            self._init_log(self.args.log)
            log = logging.getLogger(__name__)
            log.debug('--ARGS-- %s' % ' '.join(args[0]))
            log.info('seed for this run: %s' % self.args.seed)
            if by_order is True:
                log.info('will match references to genes by order')

    def _valid_ref_dir(self, ref_dir):
        """
        Looks for .fasta files in --ref_dir arg, return as list. Trick :later move to --ref flag.
        :return: .fasta reference files as list
        """
        if not path.isdir(ref_dir):
            raise self.error('invalid references directory: %s' % ref_dir)

        ref_files = list()
        for root, dirs, files in os.walk(ref_dir):
            ref_files += [path.join(root, file) for file in files if file.endswith('.fasta')]

        if len(ref_files) == 0:
            raise self.error('no .fasta references found in directory: %s' % ref_dir)
        return ref_files

    def _valid_end_ratio(self, end_ratio):
        """Checks if --end_ratio argument for trimming is in right format and meaningful."""
        try:
            ratio = [int(d) for d in end_ratio.strip().split('/')]
            if len(ratio) == 2 and ratio[0] <= ratio[1]:
                return ratio
            else:
                raise ValueError
        except ValueError:
            raise self.error('invalid end ratio defined: %s' % end_ratio)

    def _valid_start_trees(self, start_trees):
        """Checks if --start_trees argument is in the right format: [int,int] """
        try:
            start = [int(d) for d in start_trees[1:-1].split(',')]
            if len(start) == 2:
                return start
            else:
                raise ValueError
        except ValueError:
            raise self.error('invalid start trees: %s' % start_trees)

    def _valid_bootstrap(self, bootstrap):
        """Checks if --bootstrap argument is a number > 1"""
        try:
            bootstrap = int(bootstrap)
            if bootstrap > 1:
                return bootstrap
            else:
                raise ValueError
        except ValueError:
            raise self.error('Number of bootstrap trees must be an int > 1')

    def _init_log(self, filename):
        """Initializes logging."""
        log = logging.getLogger()
        log.setLevel(logging.DEBUG)

        # init verbose logging to file
        fh = logging.FileHandler(filename=filename, mode='w')
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter('%(asctime)s: %(levelname)s\t%(name)s\t%(message)s',
                                          datefmt='%Y-%m-%d %H:%M:%S'))
        log.addHandler(fh)

        # init shortened console logging
        sh = logging.StreamHandler(sys.stdout)
        sh.setLevel(logging.DEBUG if self.args.verbose is True else logging.WARNING)
        sh.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
        log.addHandler(sh)
