#!/usr/bin/env python3

import sys
if sys.version_info[0] < 3:  # or (sys.version_info[0] == 3 and sys.version_info[1] < 8):
    raise Exception("Must be using Python 3")  # .8 or later")

import argparse
import json
import time
from pathlib import Path
from typing import List, Dict

import six

try:
    import bioblend
    from bioblend.galaxy.objects import GalaxyInstance
    from bioblend.galaxy.objects.wrappers import History, HistoryDatasetAssociation, Workflow, Step
    from bioblend.galaxy.dataset_collections import CollectionDescription, CollectionElement, SimpleElement
    from bioblend.galaxy.workflows import WorkflowClient
except ImportError as e:
    print(e, file=sys.stderr)
    print("\n\033[1m\033[91mBioBlend dependency not found.\033[0m Try 'pip install bioblend'.", file=sys.stderr)
    exit(1)


upload_history_name = 'Uploaded data'
upload_history_tag = 'user_data'
workflow_name = 'IslandCompare unpacked'
application_tag = 'IslandCompare'
ext_to_datatype = {
    "genbank": "genbank", "gbk": "genbank", "embl": "embl", "gbff": "genbank", "newick": "newick", "nwk": "newick"
}

# ======== Patched bioblend functions ===========


def step__init__(self, step_dict, parent):
    super(Step, self).__init__(step_dict, parent=parent, gi=parent.gi)
    try:
        stype = step_dict['type']
    except KeyError:
        raise ValueError('not a step dict')
    if stype not in set(['data_collection_input', 'data_input', 'parameter_input', 'pause',
                         'tool', 'subworkflow']):
        raise ValueError('Unknown step type: %r' % stype)
    if self.type == 'tool' and self.tool_inputs:
        for k, v in six.iteritems(self.tool_inputs):
            # In Galaxy before release_17.05, v is a JSON-encoded string
            if not isinstance(v, six.string_types):
                break
            try:
                self.tool_inputs[k] = json.loads(v)
            except ValueError:
                break


@property
def parameter_input_ids(self):
    """
    Return the ids of parameter input steps for this workflow.
    """
    return set(id_ for id_, s in six.iteritems(self.steps)
               if s.type == 'parameter_input')


def Workflow__init__(self, wf_dict, gi=None):
    super(Workflow, self).__init__(wf_dict, gi=gi)
    missing_ids = []
    if gi:
        tools_list_by_id = [t.id for t in gi.tools.get_previews()]
    else:
        tools_list_by_id = []
    tool_labels_to_ids = {}
    for k, v in six.iteritems(self.steps):
        # convert step ids to str for consistency with outer keys
        v['id'] = str(v['id'])
        for i in six.itervalues(v['input_steps']):
            i['source_step'] = str(i['source_step'])
        step = Step(v, self)
        self.steps[k] = step
        if step.type == 'tool':
            if not step.tool_inputs or step.tool_id not in tools_list_by_id:
                missing_ids.append(k)
            tool_labels_to_ids.setdefault(step.tool_id, set()).add(step.id)
    input_labels_to_ids = {}
    for id_, d in six.iteritems(self.inputs):
        input_labels_to_ids.setdefault(d['label'], set()).add(id_)
    object.__setattr__(self, 'input_labels_to_ids', input_labels_to_ids)
    object.__setattr__(self, 'tool_labels_to_ids', tool_labels_to_ids)
    dag, inv_dag = self._get_dag()
    heads, tails = set(dag), set(inv_dag)
    object.__setattr__(self, 'dag', dag)
    object.__setattr__(self, 'inv_dag', inv_dag)
    object.__setattr__(self, 'source_ids', heads - tails)
    assert set(self.inputs) == self.data_collection_input_ids | self.data_input_ids | self.parameter_input_ids, \
        "inputs is %r, while data_collection_input_ids is %r and data_input_ids is %r" % (self.inputs, self.data_collection_input_ids, self.data_input_ids)
    object.__setattr__(self, 'sink_ids', tails - heads)
    object.__setattr__(self, 'missing_ids', missing_ids)


def get_invocations(self, workflow_id, history_id=None):
    url = self._invocations_url(workflow_id)
    if history_id:
        return self._get(url=url, params={'history_id': history_id})
    else:
        return self._get(url=url)


if bioblend.get_version() == '0.13.0':
    # Monkeypatch until https://github.com/galaxyproject/bioblend/issues/316
    Step.__init__ = step__init__
    Workflow.__init__ = Workflow__init__
    Workflow.parameter_input_ids = parameter_input_ids
    WorkflowClient.get_invocations = get_invocations

# =========================================================


class ArgumentParser(argparse.ArgumentParser):
    """
    Override default error message
    """
    def error(self, message):
        self.print_help()
        print('\n\033[1m\033[91mERROR:\033[0m ' + message, file=sys.stderr)
        exit(2)


def get_workflow(conn: GalaxyInstance) -> Workflow:
    """
    Helper to get the configured Workflow object
    :param conn: An instance of GalaxyInstance
    :return: A Workflow instance
    """
    workflows = conn.workflows.list(name=workflow_name, published=True)  # There should only be one
    if not len(workflows):
        print("IslandCompare workflow not found on host", file=sys.stderr)
        exit(1)
    return workflows[0]


def get_upload_history(conn) -> History:
    """
    Helper to get or create a history to contain uploads
    :param conn: An instance of GalaxyInstance
    :return: A History instance
    """
    histories = conn.histories.list()
    for history in histories:
        if upload_history_tag in history.tags:
            return history
    else:
        history = conn.histories.create(name=upload_history_name)
        history.tags.append(upload_history_tag)
        history.update(tags=history.tags)
        return history


def _flatten(l):
    data = []
    for datum in l:
        if isinstance(datum, list):
            data.extend(datum)
        else:
            data.append(datum)
    return data


def main(args: argparse.Namespace):
    """
    Script entrance function
    """
    conn = GalaxyInstance(args.host, args.key)
    upload_history = get_upload_history(conn)

    if args.command == 'upload':
        print("Dataset ID:", file=sys.stderr)
        hda = upload(upload_history, args.path, args.label)
        print(hda.id)

    elif args.command == 'list':
        print("ID\tLabel", file=sys.stderr)
        uploads = list_data(upload_history)
        if len(uploads):
            for data in uploads:
                print(f"{data.id}\t{data.name}")
        else:
            print("No datasets found", file=sys.stderr)

    elif args.command == 'delete':
        delete_data(upload_history, args.id)

    elif args.command == 'reference':
        print("Reference ID\tName", file=sys.stderr)
        for genome in list_reference(conn, args.query):
            print(f"{genome[1]}\t{genome[0]}")

    elif args.command == 'run':
        workflow = get_workflow(conn)
        if args.output and not args.output.is_dir():
            main.cmd.error("Output path must be existing folder")

        # Deal with bug in argparse 'extend' by switching to 'append' and flattening
        data = _flatten(args.data)
        print("Analysis ID:", file=sys.stderr)
        invocation_id, _ = invoke(workflow, args.label, [upload_history.get_dataset(id) for id in data], upload_history.get_dataset(args.newick_accession or args.newick_label), 'newick_accession' in args, args.reference_id)
        print(invocation_id)
        if args.output:
            results(workflow, invocation_id, args.output)

    elif args.command == 'runs':
        workflow = get_workflow(conn)
        print("ID\tLabel\tState", file=sys.stderr)
        for invocation in invocations(workflow):
            print(f"{invocation['id']}\t{invocation['label']}\t{invocation['state']}")  # TODO get actual state

    elif args.command == 'results':
        workflow = get_workflow(conn)
        results(workflow, args.id, args.path)

    elif args.command == 'cancel':
        workflow = get_workflow(conn)
        cancel(workflow, args.id)

    elif args.command == 'upload_run':
        workflow = get_workflow(conn)
        # Deal with bug in argparse 'extend' by switching to append and flattening
        paths = _flatten(args.paths)
        round_trip(upload_history, paths, workflow, args.label, args.output_path, args.newick_accession or args.newick_label, 'newick_accession' in args, args.reference_id)

    else:
        main.cmd.print_help()


main.cmd = ArgumentParser(description='''
IslandCompare command line interface

IslandCompare is designed to process sets of microbial genomes and present genomic island content with an interactive
visual designed to enable exploration of cross-genome genomic island content.

Datasets must be either Genbank or EMBL format.

For one off analysis use the `./islandcompare.py upload_run` command. For repeated analysis
please use the `./islandcompare.py upload`, `./islandcompare.py invoke`, and `./islandcompare.py download` commands.

If you are providing your own phylogenetic tree it must be in Newick format.
The Newick dataset can contain identifiers that either refer to the dataset accession or the dataset label.
Keep in mind that dataset labels default to the file name if not provided at upload.
''', epilog='See https://islandcompare.pathogenomics.ca/ for a GUI', formatter_class=argparse.RawTextHelpFormatter)
main.cmd.add_argument('--host', type=str, default='https://galaxy.pathogenomics.ca/', help='Galaxy instance url')
main.cmd.add_argument('--key', type=str, required=True, help='API key. Key for the default host is provided the the instructions on the Analysis page at https://islandcompare.pathogenomics.ca/analysis')
main.subcmds = main.cmd.add_subparsers(dest='command')


#upload with label
def upload(history: History, path: Path, label: str = '', type: str = None) -> HistoryDatasetAssociation:
    """
    Upload datasets
    :param history: History to upload to
    :param path: path to file to upload
    :param label: label to assign to dataset
    :param type: type of dataset as determined by Galaxy
    :return: HDA instance
    """
    if not path.is_file():
        upload.cmd.error("Invalid file path specified")

    if not label:
        label = path.name
    if not type and path.suffix and path.suffix.lstrip('.') in ext_to_datatype.keys():
        type = ext_to_datatype[path.suffix.lstrip('.')]

    if type:
        return history.upload_file(str(path.resolve()), filename=label, filetype=type)
    else:
        return history.upload_file(str(path.resolve()), filename=label)


upload.cmd_help = 'Upload datasets'
upload.cmd = main.subcmds.add_parser('upload', help=upload.cmd_help, description=upload.cmd_help)
upload.cmd.add_argument('path', type=Path, help='Path of dataset to upload')
upload.cmd.add_argument('label', type=str, nargs='?', help='Dataset label. Defaults to file name.')


#list data
def list_data(history: History, type: str = '') -> List[HistoryDatasetAssociation]:
    """
    List the data that was previously uploaded
    :param history: History instance to list
    :param type: Filter on a type of data
    :return: List of history contents
    """
    return [dataset for dataset in history.get_datasets() if not dataset.deleted and (not type or dataset.file_ext == type)]


list_data.cmd_help = 'List uploaded datasets'
list_data.cmd = main.subcmds.add_parser('list', help=list_data.cmd_help, description=list_data.cmd_help)


#delete data
def delete_data(history: History, id: str) -> None:
    """
    Delete uploaded data
    :param history: History instance containing dataset
    :param id: ID of dataset or None to delete all
    :return: None
    """
    if not id:
        history.delete()
    history.gi.gi.histories.delete_dataset(history.id, id)


delete_data.cmd_help = 'Delete uploaded datasets'
delete_data.cmd = main.subcmds.add_parser('delete', help=delete_data.cmd_help, description=delete_data.cmd_help)
delete_data.cmd.add_argument('id', metavar='ID', type=str, help='Dataset ID')


#find or list reference genomes
def list_reference(conn: GalaxyInstance, query: str ='') -> List[str]:
    """
    List all reference genomes that contain query
    :param query: Optional substring to match against species name
    :return: Reference ID and Species name
    """
    if query:
        query = query.lower()
    return [genome for genome in conn.gi.genomes.get_genomes() if not query or query in genome[0].lower() or query in genome[1].lower()]


list_reference.cmd_help = 'List available references to align drafts to'
list_reference.cmd = main.subcmds.add_parser('reference', help=list_reference.cmd_help, description=list_reference.cmd_help)
list_reference.cmd.add_argument('query', type=str, nargs='?', help='Filter on a provided substring')


def _prepare_inputs(workflow: Workflow, history_label: str, data: List[HistoryDatasetAssociation], newick: HistoryDatasetAssociation or None, accession: bool, reference_id: str) -> (Dict, History):
    """
    Helper to build workflow inputs, including preparing a output history and generating input collections
    :param workflow: Workflow instance
    :param history_label: Label for analysis
    :param data: List of HistoryDatasetAssociation instances of uploaded datasets
    :param newick: HistoryDatasetAssociation instance of uploaded newick
    :param accession: True, identifiers present in the uploaded newick are the accession. False, dataset label.
    :param reference_id: ID of reference genome to align drafts to
    :return: Tuple of dict to send as inputs and output History instance
    """
    inputs = {label: input.pop() for label, input in workflow.input_labels_to_ids.items()}
    history = workflow.gi.histories.create(history_label)

    history.tags.append(workflow.id)
    history.tags.append(application_tag)
    history.update(tags=history.tags)

    elements = [
        CollectionElement(
            name='data',
            elements=[SimpleElement({'id': datum.id, 'src': datum.SRC, 'name': datum.name}) for datum in data]
        )
    ]
    if newick:
        elements.append(CollectionElement(
            name='newick',
            elements=[SimpleElement({'id': newick, 'src': newick.SRC, 'name': newick.name})]
        ))
    input_collection = history.create_dataset_collection(CollectionDescription('input_data', type='list:list', elements=elements))
    inputs = {
        inputs['list:list of data and optional inputs']: {'id': input_collection.id, 'src': input_collection.SRC},
        inputs['Newick Identifiers']: 'False' if accession else 'True',
        inputs['Reference Genome']: reference_id or ''
    }
    return inputs, history


#invoke workflow
def invoke(workflow: Workflow, label: str, data: List[HistoryDatasetAssociation], newick: HistoryDatasetAssociation or None = None, accession: bool = True, reference_id: str = '') -> (str, History):
    """
    Invoke IslandCompare workflow
    :param workflow: Workflow instance
    :param label: Label for invocation
    :param data: List of dataset IDs to analyse
    :param newick: Optional ID for newick dataset
    :param accession: True, identifiers present in the uploaded newick are the accession. False, dataset label.
    :param reference_id: ID of reference genome to align drafts to
    :return: Invocation ID
    """
    inputs, history = _prepare_inputs(workflow, label, data, newick, accession, reference_id)
    invocation = workflow.gi.gi.workflows.invoke_workflow(workflow.id, inputs, history_id=history.id, allow_tool_state_corrections=True)

    return invocation['id'], history


invoke.cmd_flags = ArgumentParser(add_help=False)  # Make reusable arguments for upload_run
invoke.cmd_help = 'Run IslandCompare'
invoke.cmd = main.subcmds.add_parser('run', parents=[invoke.cmd_flags], help=invoke.cmd_help, description=invoke.cmd_help)
invoke.cmd_flags.add_argument('label', type=str, help='Analysis label')
invoke.cmd.add_argument('data', metavar='ID', type=str, action='append', help=argparse.SUPPRESS)
invoke.cmd.add_argument('data', metavar='ID', type=str, action='append', nargs='+', help='IDs of Genbank or EMBL datasets. Minimum of 2')
invoke.cmd_flags.add_argument('-r', type=str, dest='reference_id', help="Reference ID to align drafts to. See 'reference' command")
invoke.cmd.add_argument('-o', type=Path, dest='output', help='Wait for analysis to complete and output results to path')
invoke.cmd_newick = invoke.cmd.add_mutually_exclusive_group(required=False)
invoke.cmd_newick.add_argument('-a', type=str, metavar='NEWICK_ID', dest='newick_accession', help='Newick dataset ID containing accession identifiers')
invoke.cmd_newick.add_argument('-l', type=str, metavar='NEWICK_ID', dest='newick_label', help='Newick dataset ID containing dataset label identifiers')


#list invocations with visualize links
def invocations(workflow: Workflow) -> List[Dict[str, str]]:
    """
    List invocations of the workflow and their state
    :param workflow: Workflow instance
    :return: List of dicts of the form {id: str, label: str, state: str}
    """
    result = []
    for history in workflow.gi.histories.list():
        if not history.deleted and (workflow.id in history.tags or application_tag in history.tags):
            for invocation in workflow.gi.gi.workflows.get_invocations(workflow.id, history_id=history.id):
                result.append({'id': invocation['id'], 'state': invocation['state'], 'label': history.name})

    return result


invocations.cmd_help = 'List submitted analysis'
invocations.cmd = main.subcmds.add_parser('runs', help=invocations.cmd_help, description=invocations.cmd_help)


#download results
def results(workflow: Workflow, invocation_id: str, path: Path):
    """
    Download the outputs of a workflow invocation
    :param workflow: Workflow instance
    :param invocation_id: ID of workflow invocation
    :param path: Path to output folder
    :return: None
    """
    if not path.is_dir():
        results.cmd.error("Output path must be existing folder")

    invocation = workflow.gi.gi.workflows.show_invocation(workflow.id, invocation_id)
    history = workflow.gi.histories.get(invocation['history_id'])

    print("Waiting for results..", file=sys.stderr)
    while 'Results' not in invocation['outputs']:
        time.sleep(workflow.POLLING_INTERVAL)
        invocation = workflow.gi.gi.workflows.show_invocation(workflow.id, invocation_id)

    workflow.gi._wait_datasets([history.get_dataset(output['id']) for _, output in invocation['outputs'].items()], polling_interval=Workflow.POLLING_INTERVAL,
                               break_on_error=True)

    print("Downloading..", file=sys.stderr)
    for label, output in invocation['outputs'].items():
        dataset = history.get_dataset(output['id'])
        file_path = (path / label).with_suffix('.' + dataset.file_ext).resolve()
        workflow.gi.gi.datasets.download_dataset(output['id'], file_path, False)
        print(file_path)


results.cmd_help = 'Download analysis results'
results.cmd = main.subcmds.add_parser('download', help=results.cmd_help, description=results.cmd_help)
results.cmd.add_argument('id', metavar='ID', type=str, help='Analysis ID')
results.cmd.add_argument('path', type=Path, help='Path to output result datasets')


#delete invocation
def cancel(workflow: Workflow, invocation_id: str):
    """
    Cancel and delete a workflow invocation
    :param workflow: Workflow instance
    :param invocation_id: ID of workflow invocation
    :return: None
    """
    # Cancel still running invocations
    invocation = workflow.gi.gi.workflows.show_invocation(workflow.id, invocation_id)
    try:
        workflow.gi.gi.workflows.cancel_invocation(workflow.id, invocation_id)
    except bioblend.ConnectionError as e:
        if json.loads(e.body)['err_msg'] != 'Cannot cancel an inactive workflow invocation.':
            raise e

    # Delete output history
    history = workflow.gi.histories.get(invocation['history_id'])
    history.delete()


cancel.cmd_help = 'Cancel or delete analysis'
cancel.cmd = main.subcmds.add_parser('cancel', help=cancel.cmd_help, description=cancel.cmd_help)
cancel.cmd.add_argument('id', metavar='ID', type=str, help='Analysis ID')


# Upload and run
def round_trip(upload_history: History, paths: List[Path], workflow: Workflow, label: str, output_path: Path, newick: Path or None = None, accession: bool = True, reference_id: str = ''):
    """
    Upload data, run IslandCompare, and download results
    :param upload_history: History instance to upload datasets to
    :param paths: Paths to datasets
    :param workflow: Workflow instance to invoke
    :param label: Analysis label
    :param output_path: Path to output results to
    :param newick: Path to newick file
    :param accession: True, identifiers present in the uploaded newick are the accession. False, dataset label.
    :param reference_id: ID of reference genome to align drafts to
    :return:
    """
    start = time.time()
    for path in paths:
        if not path.is_file():
            round_trip.cmd.error("Invalid dataset path specified")

    if not output_path.is_dir():
        round_trip.cmd.error("Output path must be existing folder")

    print("Uploading..", file=sys.stderr)
    uploads = []
    for path in paths:
        uploads.append(upload(upload_history, path))

    if newick:
        newick = upload(upload_history, newick)

    print("Running..", file=sys.stderr)
    invocation_id, history = invoke(workflow, label, uploads, newick, accession, reference_id)

    results(workflow, invocation_id, output_path)

    print(f"Wall time: {(time.time() - start)/60} minutes", file=sys.stderr)
    # Clean up
    for hda in uploads:
        hda.delete(purge=True)

    if newick:
        newick.delete(purge=True)
    history.delete(purge=True)


round_trip.cmd_help = 'Upload, run analysis, and download results'
round_trip.cmd = main.subcmds.add_parser('upload_run', parents=[invoke.cmd_flags], help=round_trip.cmd_help, description=round_trip.cmd_help)
round_trip.cmd.add_argument('paths', metavar='path', type=Path, action='append', help=argparse.SUPPRESS)
round_trip.cmd.add_argument('paths', metavar='path', type=Path, action='append', nargs='+', help='Paths to individual Genbank or EMBL datasets. Minimum of 2')
round_trip.cmd.add_argument('output_path', type=Path, help='Path to output result datasets')
round_trip.cmd_newick = round_trip.cmd.add_mutually_exclusive_group(required=False)
round_trip.cmd_newick.add_argument('-a', type=str, metavar='NEWICK_PATH', dest='newick_accession', help='Newick dataset ID containing accession identifiers')
round_trip.cmd_newick.add_argument('-l', type=str, metavar='NEWICK_PATH', dest='newick_label', help='Newick dataset ID containing dataset label identifiers')


if __name__ == '__main__':
    try:
        main(main.cmd.parse_args())
    except bioblend.ConnectionError as e:
        main.cmd.error(json.loads(e.body)['err_msg'])
