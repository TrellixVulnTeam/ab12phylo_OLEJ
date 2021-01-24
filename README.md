# AB12PHYLO

![PyPI license](https://img.shields.io/pypi/l/ansicolortags.svg) 
![gitlab version](https://img.shields.io/static/v1?label=version&message=0.3a.20&color=blue&style=flat)
![Python version](https://img.shields.io/static/v1?label=python&message=3.6&color=orange&style=flat&logo=python)

[AB12PHYLO](https://gitlab.lrz.de/leokaindl/ab12phylo/) is an integrated, easy-to-use pipeline for Maximum Likelihood (ML) phylogenetic tree inference from ABI sequencing data. 
At its core, AB12PHYLO runs parallelized instances of [RAxML-NG](https://github.com/amkozlov/raxml-ng) (Kozlov et al. 2019) and a BLAST search in a reference database. 
It enables visual, effortless sample identification based on phylogenetic position and sequence similarity, as well as population subset selection aided by metrics like Tajima's D for estimations on ongoing evolution.
 
AB12PHYLO was developed to identify plant pathogen populations possibly under balancing selection with *Solanum chilense*, especially in the genus *Alternaria*. With multi-gene phylogenies remaining a widely-used method in spite of the rise of whole-genome sequencing, future application on fungal phytopathogens or host plants appears likely.


## Installation
 
First, clone the AB12PHYLO repository:
 
```bash
git clone https://gitlab.lrz.de/leokaindl/ab12phylo.git
```
All [external tools](#external-tools) are in the [Bioconda](https://anaconda.org/bioconda/repo) channel, which can make installation a bit more comfortable. To create a new or activate an existing python3 [conda](https://docs.conda.io/) environment:
```bash
conda create -n <your_python3_conda_env> python=3
conda activate <your_python3_conda_env>
```
Then install the external tools in one go:

```bash

# might not work 
conda install -c bioconda "blast>=2.9.0" "raxml-ng>=1.0.1" 

# for development
conda install -c conda-forge pygobject gtk3                        

# but
conda install -c bioconda "iqtree>=2.0.3" "fasttree>=2.1.10" "gblocks=0.91b" mafft clustalo muscle
```

This will require you to `conda activate <your_python3_conda_env>` anytime you want to run AB12PHYLO. Alternatively, installing BLAST+ and your preferred MSA tool will suffice and should be easy.
 
Install AB12PHYLO and all its [dependencies](#dependencies) via `pip` or `pip3` to your regular python3:
 
 ```bash
cd ab12phylo
pip install --upgrade pip
pip install .
```


## Getting Started

As AB12PHYLO is primarily a command line tool, you might want to take a look at its interface by running `ab12phylo -h`.


#### Test run
The pipeline comes with its own test data set. If you pass `-test`, it will read options from an auxiliary (or backup) config file at `<ab12phylo_root>/ab12phylo/config/test_config.yaml` and run on these. The test run is set to `--verbose` and will run `--no_remote` BLAST search.


#### Basic options
A simple real-world invocation might look like this:

```bash
ab12phylo -abi <seq_dir> \
    -csv <wellsplates_dir> \
    -g <barcode_gene> \
    -rf <ref.fasta> \
    -bst 1000 \
    -dir <results>
```
where:
* `<seq_dir>` contains all input ABI trace files, ending in `.ab1`
* `<wellsplates_dir>` contains the `.csv` mappings of user-defined IDs to sequencer's isolate coordinates
* `<barcode_gene>` was sequenced. more [info](#genes-and-references)
* `<ref.fasta>` contains full GenBank reference records [like this](https://www.ncbi.nlm.nih.gov/nuccore/AF347033.1?report=fasta&log$=seqview&format=text)
* 1000 `-bst` = `--bootstrap` trees will be generated
* `<results>` is where results will be  


#### Detailed settings
AB12PHYLO has reasonably smart defaults while allowing fine-grained access to its settings:

```bash
ab12phylo -rf <ref.fasta> \
    -db <your_own> \
    -dbpath <your_dir> \
    -abiset <whitelist> \
    -regex_3 <"rx1" "rx2" "rx3"> \
    -algo <mafft-clustalo-muscle-tcoffee> \
    -gbl balanced \
    -local \
    -i \
    -p1

ab12phylo -p2 \
    -bst 1000 \
    -st [32,16]  \
    -s 4 \
    -v 
```
* **default:** AB12PHYLO will search for `.ab1` and `.csv` files in or below the current working directory
* **default:** use the `./results` subdirectory
* **default:** use the `GTR+Γ` model of evolution
* use `<your_own>` [BLAST+ database](#blast-database); in `<your_dir>`
* only trace files listed in the [`<whitelist>`](#results--motif-search) will be read
* plate number, gene name and well will be parsed from the `.ab1` filename using these three [RegEx](#regex).
* `-algo` will generate the MSA: `mafft`, `clustalo`, `muscle` or `t_coffee`
* `-gbl` sets `Gblocks` MSA trimming mode: `skip`, `relaxed`, `balanced` or `strict`
* `-local` skips online BLAST for sequences not in the local BLAST+ db and [read why](#blast-api)
* `-i` or `--info` shows some more run details in the console
* `-p1` run only part one, up until BLAST; also generates an MView HTML of the MSA to find funny sequences


For the second invocation:
* `-p2` run part two of AB12PHYLO, starting with RAxML-NG
* `-st`: ML tree searches from `32` random and `16` parsimony-based starting trees
* `-s` fixes the random `--seed` to `4` for reproducibility
* `-v` or `--verbose` shows all logged events in the console


## Results + Motif Search
Once ML tree inference, bootstrapping and BLAST has finished, the pipeline will display a `result.html` in your web browser. This page contains a form that allows **Motif search** across node attributes and calculates diversity metrics for the matching subset/subtree. Entering a space `' '` should match all samples, and entering multiple motifs separated by commas `,` will select all leaves that match at least one motif. 

To select a subtree, enter a motif that matches several leaves or at least two separate specific leaf motifs, with one of them as far left as possible. Entering a single, specific motif for a subtree search can be used to find the index of a node for tree modifications like rooting.

Once you hit `MATCH` or `SUBTREE`, the CGI script in the package will highlight the selection in the tree, as well as compute and display diversity statistics for this 'population'. It will also write and link a file with all selected sample IDs or the paths of the original `.ab1` files in the `/query` subdirectory, which can be used as a whitelist file for a subsequent subset analysis run. Pass it via `-sampleset` if using sample IDs, or via `-abiset` if using file paths. File paths are recommended to reliably exclude outlier versions with identical base ID.

If results are moved or sent, motif search will be possible by using `ab12phylo-view` or starting a CGI server in the directory via `python3 -m http.server --cgi <port>`. Find the port on the intro tab.


## BLAST
If none of the smaller BLAST+ databases are sufficient for your search, you are better of with a [web BLAST](https://blast.ncbi.nlm.nih.gov/Blast.cgi). Collate your data by running `-p1 --no_BLAST`, then upload the `<gene>/<gene>.fasta` for the gene you wish to use for species annotation. Pass the result via `--BLAST_xml`. You can pass more than one file; AB12PHYLO will use the last annotation for a sample and ignore everything but the first hit.


#### BLAST API
AB12PHYLO is perfectly capable of running online BLAST searches without a BLAST+ installation. However, this is not a suitable main BLAST strategy as BLAST API queries are de-prioritised after just a few attempts. Accordingly, if several runs are attempted on the same data set, passing the `--no_remote` flag will use data from an earlier run by default. You can also leave out species annotation by skipping BLAST entirely with `--no_BLAST`.


#### BLAST+ Database
Sometimes, this pipeline might run headless on a server. To keep it from running head-first in a firewall when it attempts to update its BLAST+ database via FTP, please pre-supply an unzipped, ready-to-use BLAST+ database via `-dbpath` (and `-db` name). Find databases on the [NCBI website](https://ftp.ncbi.nlm.nih.gov/blast/db/), but [web BLAST](https://blast.ncbi.nlm.nih.gov/Blast.cgi) and `--BLAST_xml` might be both easier and faster.


## Visualization

#### ab12phylo-visualize + ab12phylo-view
`ab12phylo-visualize` will re-plot phylogenies and render a new `results.html`. An end user may use this to switch [support values](#support-values) or plot an MSA visualization with `-msa-viz`. This will take some rendering time for wider alignments.
 `ab12phylo-view` shows results of a previous run in a browser, with motif search enabled. Both commands accept a path to the AB12PHYLO results or default to `.`, and are equivalent to appending to the original `ab12phylo` call.

```bash
ab12phylo-view <result_folder>
# or
cd <results_folder>
ab12phylo-view
# or 
ab12phylo -c <my-config.yaml> -bst 1000 (...) -view
```


#### Support Values
For visualization, you can pick either Felsenstein Bootstrap Proportions `FBP` or [Transfer Bootstrap Expectation](https://doi.org/10.1038/s41586-018-0043-0) `TBE` support values with `-metric`. Newick tree files for both types are generated anyway, so switching the support value metric only requires re-running `ab12phylo-visualize`.


#### MSA visualization
AB12PHYLO can plot an additional rectangular tree with an MSA visualization next to it by passing `-msa_viz`. This is single-threaded and takes some extra time for larger MSAs. If you run `-p1`, you can visually inspect the MView HTML of the alignment for outliers already without having to wait for the entire pipeline.


#### Tree modifications
You can `-drop_nodes`, `-replace_nodes` or subtrees with a placeholder, or `-root` the tree with an outgroup sequence. These options accept integer node indices from [motif search](#results--motif-search).

Also see the `VISUALIZATION` section of `--help`.

## Advanced use

#### Remote runs
[tmux](https://askubuntu.com/questions/8653/how-to-keep-processes-running-after-ending-ssh-session/220880#220880) and `--headless` are highly recommended for remote runs, as well as [pre-supplying a BLAST+ db](#blast-database), adapting or replacing the [YAML](https://yaml.org/) config file and setting a fixed seed for reproducibility. 


#### Genes and References
If data for several genes is supplied, AB12PHYLO will restrict the analysis to samples that are present for all genes. If this causes a lot of samples to be dropped, it might be worth leaving out a gene entirely by setting `-g` = `--genes` manually. If you somehow have `No samples shared across all genes`, there might be some trace files that seemingly belongs to another gene.

Passing references is closely inter-linked: If a directory of reference files is supplied via `-rd` = `--ref_dir`, the package will try to match the `.FASTA` files inside to genes *by their filename*. For example, `ITS1F.fasta` will be matched to trace data from the *ITS1F* gene. Alternatively, an ordered list of reference files can be passed via `-rf` = `--ref`, and file names will be ignored. 

If you're feeling this neat and precise and set both the genes and individual references, be careful: The pipeline will then deliberately match references and genes *by order*. Therefore, this will make a mess:

```bash
-g ITS1F OPA10 -rf ../opa10.fasta ITS1F.phy
```


#### RegEx
If you provide wellsplates mappings, AB12PHYLO will parse plate number, gene name and the sequencer's isolate coordinates from the `.ab1` filename with a RegEx and fetch the user-defined ID from the corresponding `.csv` look-up table. To use your own, please consult `--help` and try out your RegEx [here](https://regex101.com/r/Yulwlf/3) or [there](https://regex101.com/r/Yulwlf/5). From a bash shell, enclose the terms with double quotes `"`. The wellsplate number or ID is also parsed from the `.csv` filename with a RegEx.

Provide a RegEx to `--regex_rev` and AB12PHYLO will look out for reverse reads, and add only their reverse complement to the data set.


#### MSA clients and T-Coffee
As of June 2020, there is no T-Coffee package for python3.8 on Bioconda. The MSA algorithm can however still be used by using the EMBL-EBI [online tool](https://www.ebi.ac.uk/Tools/msa/) and the API client included in AB12PHYLO. If it doesn't work, try [refreshing](https://www.ebi.ac.uk/seqdb/confluence/display/JDSAT/T-coffee+Help+and+Documentation) the client.


#### Log File
If you're having trouble, look at the log file! It will be in your results directory and named like `ab12phylo[|-p1|-p2][-view|-viz]?.log`. Alternatively, you can set the `--verbose` flag and get the same information in real-time to your commandline. Your choice!


## Dependencies
[Biopython](https://biopython.org/wiki/Download), [NumPy](https://numpy.org/), [pandas](https://pandas.pydata.org/docs/getting_started/install.html), [Toytree](https://toytree.readthedocs.io/en/latest/), [Toyplot](https://toyplot.readthedocs.io/en/stable/), [PyYAML](https://pyyaml.org/wiki/PyYAML), [lxml](https://lxml.de/), [xmltramp2](https://pypi.org/project/xmltramp2/) and [Jinja2](https://jinja.palletsprojects.com/en/2.11.x/intro/#installation)


## External Tools
* [BLAST+](https://ftp.ncbi.nlm.nih.gov/blast/executables/blast+/LATEST/) version >=2.9 *(optional, recommended if small or custom [database](#blast-database))*
* [RAxML-NG](https://github.com/amkozlov/raxml-ng/) *(optional, included)*
* an MSA tool: [MAFFT](https://mafft.cbrc.jp/alignment/software/), [Clustal Omega](http://www.clustal.org/omega/), [MUSCLE](https://www.drive5.com/muscle/downloads.htm) or [T-Coffee](http://www.tcoffee.org/Projects/tcoffee/index.html#DOWNLOAD) *(optional, **slow** online clients for [EMBL interface](https://www.ebi.ac.uk/Tools/msa/) included)*
* [Gblocks](http://molevol.cmima.csic.es/castresana/Gblocks.html) for MSA trimming *(optional, included)*
