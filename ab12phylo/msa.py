# 2020 Leo Kaindl

"""
This module builds a multiple sequence alignment for each gene and concats
them into one :code:`FASTA` file as input for the :class:`raxml` module.
"""

import os
import sys
import shutil
import logging
import random
import subprocess

from os import path
from time import time, sleep

from Bio import SeqIO


class msa_build:
    """Builds a Multiple Sequence Alignment"""

    def __init__(self, args, seq_counts):
        self.log = logging.getLogger(__name__)
        self.dir = args.dir
        self.genes = args.genes
        self.algo = args.msa_algo
        self.email = args.user
        self.msa = args.msa
        self.sep = args.sep
        self.missing_samples = args.missing_samples
        self.tools_path = path.join(path.abspath(path.dirname(__file__)), 'tools')

        # look for pre-installed version of selected algorithm
        self.binary = shutil.which(args.msa_algo)

        # build MSAs
        for gene in self.genes:
            if self.binary is not None:
                self.build_local(gene)
            else:
                self.build_remote(gene)
                sleep(5)

            # trim MSAs using Gblocks
            self.trim_msa(gene, seq_counts[gene], args.gblocks)

        # concat MSAs
        self.concat_msa()

    def build_local(self, gene):
        """Build MSAs locally using a pre-installed binary."""
        log_file = path.join(self.dir, gene, self.algo + '.log')
        fasta = path.join(self.dir, gene, gene + '.fasta')
        raw_msa = path.join(self.dir, gene, gene + '_raw_msa.fasta')
        self.log.debug('preparing %s MSA run' % self.algo)

        if self.algo == 'mafft':
            arg = '%s --thread %d --auto  %s > %s' \
                  % (self.binary, os.cpu_count(), fasta, raw_msa)

        elif self.algo == 'clustalo':
            arg = '%s --in %s --out %s --outfmt fasta --threads %d --force --verbose --auto' \
                  % (self.binary, fasta, raw_msa, os.cpu_count())

        elif self.algo == 'muscle':
            arg = '%s -in %s -out %s' \
                  % (self.binary, fasta, raw_msa)

        elif self.algo == 't_coffee':
            arg = '%s -in %s -out %s -output fasta_aln -type dna ' \
                  % (self.binary, fasta, raw_msa)
        else:
            assert False

        self._run(arg, log_file, 'pre-installed %s' % self.algo)

    def build_remote(self, gene):
        """Builds an MSA online using an EBI API client"""
        log_file = path.join(self.dir, gene, self.algo + '.log')
        fasta = path.join(self.dir, gene, gene + '.fasta')
        raw_msa = path.join(self.dir, gene, gene + '_raw_msa.fasta')

        self.log.warning('running %s online' % self.algo.upper())

        if self.algo == 't_coffee':
            self.algo = 'tcoffee'

        # create base call
        arg = 'python3 %s --email %s --outfile %s --sequence %s ' \
              % (path.join(self.tools_path, 'MSA_clients', self.algo + '.py'),
                 self.email, path.join(self.dir, gene, 'msa'), fasta)

        # adapt for specific algorithm
        if self.algo == 'mafft':
            arg += '--stype dna'
        elif self.algo == 'clustalo':
            arg += '--stype dna --outfmt fa'
        elif self.algo == 'muscle':
            arg += '--format fasta'
        elif self.algo == 'tcoffee':
            arg += '--stype dna --format fasta_aln'

        # build an MSA for each gene
        self._run(arg, log_file, 'online %s' % self.algo)
        shutil.move(path.join(self.dir, gene, 'msa.aln-fasta.fasta'), raw_msa)

    def trim_msa(self, gene, seq_count, gblocks_mode):
        """
        Trims an MSA using Gblocks, using a pre-installed or deployed version.

        :param gene: this helps find the right files to trim
        :param seq_count: for computing settings
        :param gblocks_mode: can be ['skip', 'relaxed', 'balanced', 'semi_strict', 'strict']
        :return:
        """
        log_file = path.join(self.dir, gene, 'gblocks.log')
        raw_msa = path.join(self.dir, gene, gene + '_raw_msa.fasta')

        if gblocks_mode == 'skip':
            shutil.copy(raw_msa, path.join(self.dir, gene, gene + '_msa.fasta'))
            self.log.info('skipped Gblocks trimming, only copied file')

        else:
            # look for local Gblocks
            binary = shutil.which('Gblocks')
            local = True
            if binary is None:
                # pick deployed Gblocks
                binary = path.join(self.tools_path, 'Gblocks_0.91b', 'Gblocks')
                local = False

            # set Gblocks options

            b4 = 5
            if gblocks_mode == 'relaxed':
                # set the minimal permissible minimum number of identical
                # sequences per position to define a conserved position
                cons = seq_count // 2 + 1
                # minimal number for a conserved flanking position
                flank = cons
                # keep no, half or all gap positions
                gaps = ['n', 'h', 'a'][1]
                self.log.info('running relaxed Gblocks')

            elif gblocks_mode == 'balanced':
                cons = seq_count // 2 + 1
                flank = min(seq_count // 4 * 3 + 1, seq_count)
                gaps = ['n', 'h', 'a'][1]
                self.log.info('running balanced Gblocks')

            elif gblocks_mode == 'default':
                cons = seq_count // 2 + 1
                flank = min(int(seq_count * 0.85) + 1, seq_count)
                gaps = ['n', 'h', 'a'][0]
                b4 = 10
                self.log.info('running Gblocks at default settings')

            else:
                cons = int(seq_count * 0.9)
                flank = cons
                gaps = ['n', 'h', 'a'][0]
                self.log.info('running strict Gblocks')

            # create base call
            arg = '%s %s -t=d -b2=%d -b1=%d -b4=%d -b5=%s -e=.txt -d=n -s=y -p=n; exit 0' \
                  % (binary, raw_msa, flank, cons, b4, gaps)  # don't swap order!
            # MARK the -d=n sets the mode to nucleotides ... adapt?
            self._run(arg, log_file, 'pre-installed Gblocks' if local else 'out-of-the-box Gblocks')
            shutil.move(raw_msa + '.txt', path.join(self.dir, gene, gene + '_msa.fasta'))

    def concat_msa(self):
        """Reads all trimmed MSAs to memory, then iterates over samples, writes concatenated MSA."""
        self.log.debug('concatenating per-gene MSAs')
        # read in all MSAs using SeqIO
        all_records = {gene: {record.id: record.upper() for record in SeqIO.parse(
            path.join(self.dir, gene, gene + '_msa.fasta'), 'fasta')} for gene in self.genes}

        # get the length of the trimmed concat MSA
        msa_len = 0
        for gene in all_records.keys():
            msa_len += len(random.choice(list(all_records[gene].values())))

        missing_genes = {gene: list() for gene in self.genes}

        with open(self.msa, 'w') as msa:
            shared = 0
            # iterate over samples available for first gene
            for sample_id in set(all_records[self.genes[0]]):
                # get SeqRecord for first gene
                record = all_records[self.genes[0]].pop(sample_id)

                skip = False
                # append other genes
                for gene in self.genes[1:]:
                    try:
                        record += self.sep  # to visually separate genes in the MSA
                        record += all_records[gene].pop(sample_id)
                    except KeyError:
                        missing_genes[gene].append(sample_id)
                        skip = True
                # write to file
                if not skip:
                    shared += 1
                    SeqIO.write(record, msa, 'fasta')
        if len(self.genes) > 1:
            if shared == 0:
                self.log.error('No samples shared across all genes.')
                exit(1)
            else:
                self.log.info('finished writing concat MSA with %d entries' % shared)
        else:
            if msa_len == 0:
                self.log.error('No conserved sites found. Please try a more relaxed trimming mode!')
                exit(1)
            self.log.info('copied MSA to result root')
        self.log.info('MSA shape: %dx%d' % (msa_len, shared))

        # any remaining samples were missing from first gene
        [missing_genes[self.genes[0]].extend(all_records[gene].keys()) for gene in self.genes[1:]]

        # write info about missing samples to file and log
        with open(self.missing_samples, 'w') as fh:
            fh.write('gene\tmissing samples\n')
            for gene, samples in missing_genes.items():
                _collect = ', '.join(set(samples))
                if _collect == '':
                    _collect = 'None'
                fh.write('%s\t%s\n' % (gene, _collect))
                self.log.info('samples missing from %s: %s' % (gene, _collect))

    def _run(self, arg, log_file, info):
        """Runs a command and writes output to log-file."""
        self.log.debug(arg)
        start = time()
        with open(log_file, 'w') as log_handle:
            try:
                subprocess.run(arg, shell=True, check=True, stdout=log_handle, stderr=log_handle)
            except (OSError, subprocess.CalledProcessError) as e:
                self.log.exception('returned: ' + str(e.returncode)
                                   + e.output.decode('utf-8') if e.output is not None else '')
                sys.exit(1)
        self.log.debug('%.2f seconds for %s' % (time() - start, info))
