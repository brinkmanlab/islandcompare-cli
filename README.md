IslandCompare Command Line Interface
====================================

IslandCompare is designed to process sets of microbial genomes and present genomic island content with an interactive
visual designed to enable exploration of cross-genome genomic island content.

This script provides a command line interface to a IslandCompare deployment.

The default host is https://galaxy.pathogenomics.ca/

You will need an API key to access the service. It can be found on the Analysis page at
https://islandcompare.pathogenomics.ca/analysis

For one off analysis use the `./islandcompare.py upload_run` command. For repeated analysis
please use the `./islandcompare.py upload`, `./islandcompare.py invoke`, and `./islandcompare.py download` commands.

Help:
-------------

```
usage: islandcompare.py [-h] [--host HOST] --key KEY {upload,list,delete,reference,run,runs,download,cancel,upload_run} ...

IslandCompare command line interface

IslandCompare is designed to process sets of microbial genomes and present genomic island content with an interactive
visual designed to enable exploration of cross-genome genomic island content.

Datasets must be either Genbank or EMBL format.

For one off analysis use the `./islandcompare.py upload_run` command. For repeated analysis
please use the `./islandcompare.py upload`, `./islandcompare.py invoke`, and `./islandcompare.py download` commands.

If you are providing your own phylogenetic tree it must be in Newick format.
The Newick dataset can contain identifiers that either refer to the dataset accession or the dataset label.
Keep in mind that dataset labels default to the file name if not provided at upload.

positional arguments:
  {upload,list,delete,reference,run,runs,download,cancel,upload_run}
    upload              Upload datasets
    list                List uploaded datasets
    delete              Delete uploaded datasets
    reference           List available references to align drafts to
    run                 Run IslandCompare
    runs                List submitted analysis
    download            Download analysis results
    cancel              Cancel or delete analysis
    upload_run          Upload, run analysis, and download results

optional arguments:
  -h, --help            show this help message and exit
  --host HOST           Galaxy instance url
  --key KEY             API key. Key for the default host is provided on the Analysis page at https://islandcompare.pathogenomics.ca/analysis

See https://islandcompare.pathogenomics.ca/ for a GUI
```

```
usage: islandcompare.py upload [-h] path label
Upload datasets
positional arguments:
  path        Path of dataset to upload
  label       Dataset label. Defaults to file name.
optional arguments:
  -h, --help  show this help message and exit
```

```
usage: islandcompare.py list [-h]
List uploaded datasets
optional arguments:
  -h, --help  show this help message and exit
```

```
usage: islandcompare.py delete [-h] ID
Delete uploaded datasets
positional arguments:
  ID          Dataset ID
optional arguments:
  -h, --help  show this help message and exit
```

```
usage: islandcompare.py reference [-h] [query]
List available references to align drafts to
positional arguments:
  query       Filter on a provided substring
optional arguments:
  -h, --help  show this help message and exit
```

```
usage: islandcompare.py run [-h] [-o OUTPUT] [-a NEWICK_ID | -l NEWICK_ID]
                           ID [ID ...]
Run IslandCompare
positional arguments:
  ID            IDs of Genbank or EMBL datasets. Minimum of 2
optional arguments:
  -h, --help    show this help message and exit
  -o OUTPUT     Wait for analysis to complete and output results to path
  -a NEWICK_ID  Newick dataset ID containing accession identifiers
  -l NEWICK_ID  Newick dataset ID containing dataset label identifiers
```

```
usage: islandcompare.py runs [-h]
List submitted analysis
optional arguments:
  -h, --help  show this help message and exit
```

```
usage: islandcompare.py download [-h] ID path
Download analysis results
positional arguments:
  ID          Analysis ID
  path        Path to output result datasets
optional arguments:
  -h, --help  show this help message and exit
```

```
usage: islandcompare.py cancel [-h] ID
Cancel or delete analysis
positional arguments:
  ID          Analysis ID
optional arguments:
  -h, --help  show this help message and exit
```

```
usage: islandcompare.py upload_run [-h] [-r REFERENCE_ID]
                                  [-a NEWICK_PATH | -l NEWICK_PATH]
                                  label path [path ...] output_path
Upload, run analysis, and download results
positional arguments:
  label            Analysis label
  path             Paths to Genbank or EMBL datasets. Minimum of 2
  output_path      Path to output result datasets
optional arguments:
  -h, --help       show this help message and exit
  -r REFERENCE_ID  Reference ID to align drafts to. See 'reference' command
  -a NEWICK_PATH   Newick dataset ID containing accession identifiers
  -l NEWICK_PATH   Newick dataset ID containing dataset label identifiers
```