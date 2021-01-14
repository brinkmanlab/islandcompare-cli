IslandCompare Command Line Interface
====================================

IslandCompare is designed to process sets of microbial genomes and present genomic island content with an interactive
visual designed to enable exploration of cross-genome genomic island content.

This script provides a command line interface to a IslandCompare deployment.

The default host is https://galaxy.islandcompare.ca/

You will need an API key to access the service. It can be found in the instructions on the Analysis page at
https://islandcompare.ca/analysis

For one off analysis use the `./islandcompare.py upload_run` command. For repeated analysis
please use the `./islandcompare.py upload`, `./islandcompare.py run`, and `./islandcompare.py download` commands.


Tutorial
--------
For one off analysis you will want to use the `upload_run` command:
```shell
$ mkdir output
$ ./islandcompare.py --key MYAPIKEY upload_run 'Analysis label' ./path/to/data/*.gbk ./output/
Uploading..
Running..
Analysis ID:
123456789AB
Waiting..
```
`'Analysis label'` is a helpful label to identify the analysis in the `runs` command. In the event you lose connection, 
you can resume waiting using `./islandcompare.py --key MYAPIKEY download 123456789AB ./output/`. 
'123456789AB' is the analysis id output when the job was initially ran.

BASH and other compatible shells will automatically expand the 
[glob pattern](https://www.linuxjournal.com/content/pattern-matching-bash) `./path/to/data/*.gbk` to a space separated list of 
the matching files. You can use this to avoid having to write out each file path individually.

`upload_run` will delete all uploaded data and the analysis upon completion. This allows you to run many analyses in series
without having to worry about quotas.

The remaining commands are mostly useful when calling islandcompare.py from a script. This allows fine grained control
of the upload, run, and download process. One important thing to note is that the output of each of the commands sends
the human readable messages and headers to stderr while the pertinent information you will want to capture is sent to stdout.

This allows doing something similar to the following in a script:
```bash
#!/usr/bin/env bash
KEY='MYAPIKEY'
DATASETS=()
# Upload
for file in ./data/*.gbk
do
    DATASETS+=(`./islandcompare.py --key $KEY upload $file`)
done

# Run
RUN=`./islandcompare.py --key $KEY run 'batch job' $DATASETS`

# Wait and download
./islandcompare.py --key $KEY download $RUN ./output/
```


Help
-------------

```
usage: islandcompare.py [-h] [--host HOST] --key KEY {upload,list,delete,reference,run,runs,download,cancel,upload_run} ...

IslandCompare command line interface

IslandCompare is designed to process sets of microbial genomes and present genomic island content with an interactive
visual designed to enable exploration of cross-genome genomic island content.

Datasets must be either Genbank or EMBL format.

For one off analysis use the `./islandcompare.py upload_run` command. For repeated analysis
please use the `./islandcompare.py upload`, `./islandcompare.py run`, and `./islandcompare.py download` commands.

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
    errors              Get any errors during analysis
    upload_run          Upload, run analysis, and download results

optional arguments:
  -h, --help            show this help message and exit
  --host HOST           Galaxy instance url
  --key KEY             API key. Key for the default host is provided on the Analysis page at https://islandcompare.ca/analysis

See https://islandcompare.ca/ for a GUI
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
usage: islandcompare.py run [-h] [-r REFERENCE_ID] [-o OUTPUT] [-a NEWICK_ID | -l NEWICK_ID] analysis_label ID [ID ...]

Run IslandCompare

positional arguments:
  analysis_label   Analysis label
  ID               IDs of Genbank or EMBL datasets as returned by the upload or list commands. Minimum of 2

optional arguments:
  -h, --help       show this help message and exit
  -r REFERENCE_ID  Reference ID to align drafts to. See 'reference' command
  -o OUTPUT        Wait for analysis to complete and output results to path
  -a NEWICK_ID     Newick dataset ID containing accession identifiers
  -l NEWICK_ID     Newick dataset ID containing dataset label identifiers
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
usage: islandcompare.py errors [-h] ID

Get any errors during analysis

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
