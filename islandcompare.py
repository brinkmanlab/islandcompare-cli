#!/usr/bin/env python3

import sys
if sys.version_info[0] < 3:
    raise Exception("Must be using Python 3")

import requests
import traceback
import argparse
import json
import os
import time
import re
from pathlib import Path
from collections import namedtuple
from typing import List, Dict
from urllib.parse import urljoin

try:
    import bioblend
    if bioblend.get_version() != '0.14.0':
        raise ImportError("IslandCompare-CLI requires BioBlend v0.14.0")
    from bioblend.galaxy.objects import GalaxyInstance
    from bioblend.galaxy.objects.wrappers import History, HistoryDatasetAssociation, Workflow, Step
    from bioblend.galaxy.dataset_collections import CollectionDescription, CollectionElement, HistoryDatasetCollectionElement, HistoryDatasetElement
    from bioblend.galaxy.workflows import WorkflowClient
    from bioblend.galaxy.histories import HistoryClient
    from bioblend.galaxy.datasets import DatasetClient
    from bioblend.galaxy.jobs import JobsClient
    from bioblend.galaxy.invocations import InvocationClient
except ImportError as e:
    print(e, file=sys.stderr)
    print("\n\033[1m\033[91mBioBlend dependency not found.\033[0m Try 'pip install bioblend==0.14.0'.", file=sys.stderr)
    exit(1)

__version__ = '0.1.0'

#import logging
#logging.basicConfig(level=logging.DEBUG)

upload_history_name = 'Uploaded data'
upload_history_tag = 'user_data'
workflow_tag = 'islandcompare'
workflow_owner = 'brinkmanlab'
application_tag = 'IslandCompare'
ext_to_datatype = {
    "genbank": "genbank", "gbk": "genbank", "embl": "embl", "gbff": "genbank", "newick": "newick", "nwk": "newick"
}

WorkflowClient.set_max_get_retries(5)
HistoryClient.set_max_get_retries(5)
DatasetClient.set_max_get_retries(5)
JobsClient.set_max_get_retries(5)
InvocationClient.set_max_get_retries(5)


# ======== Patched bioblend functions ===========
def get_invocations(self, workflow_id, history_id=None, user_id=None, include_terminal=True, limit=None, view='collection', step_details=False):
    url = self._invocations_url(workflow_id)
    params = {'include_terminal': include_terminal, 'view': view, 'step_details': step_details}
    if history_id: params['history_id'] = history_id
    if user_id: params['user_id'] = user_id
    if limit: params['limit'] = limit
    return self._get(url=url, params=params)


WorkflowClient.get_invocations = get_invocations
Workflow.BASE_ATTRS += ('owner', 'number_of_steps', 'show_in_tool_panel', 'latest_workflow_uuid')
# =========================================================


class ArgumentParser(argparse.ArgumentParser):
    """
    Override default error message
    """
    def error(self, message):
        self.print_help()
        print('\n\033[1m\033[91mERROR:\033[0m ' + message, file=sys.stderr)
        exit(2)


class BlockingWorkflowError(Exception):
    pass


def get_workflow(conn: GalaxyInstance) -> Workflow:
    """
    Helper to get the configured Workflow object
    :param conn: An instance of GalaxyInstance
    :return: A Workflow instance
    """
    workflows = conn.workflows.list(published=True)
    if not len(workflows):
        print("IslandCompare workflow not found on host", file=sys.stderr)
        exit(1)
    for workflow in workflows:
        if workflow.owner == workflow_owner and workflow_tag in workflow.tags:
            return workflow

    # Fall back to any owner
    for workflow in workflows:
        if workflow_tag in workflow.tags:
            return workflow

    print("IslandCompare workflow not found on host", file=sys.stderr)
    exit(1)


def get_upload_history(conn) -> History:
    """
    Helper to get or create a history to contain uploads
    :param conn: An instance of GalaxyInstance
    :return: A History instance
    """
    histories = conn.gi.histories.get_histories()
    for history in histories:
        if upload_history_tag in history['tags']:
            return conn.histories.get(history['id'])
    else:
        history = _retryConnection(conn.histories.create, name=upload_history_name)
        history.tags.append(upload_history_tag)
        _retryConnection(history.update, tags=history.tags)
        return history


def get_invocation_state(history, invocation_id) -> str:
    """
    Helper to determine invocation overall state
    :param history: History instance associated with invocation
    :param invocation_id: Id of workflow invocation
    :return: 'done', 'running' or 'error'
    """

    # Check for blocking errors
    if history.state_details['error'] > 0 or history.state == 'error':
        for state in ('new', 'upload', 'queued', 'running', 'setting_metadata'):
            if history.state_details[state] > 0:
                return 'running'

    invocation = history.gi.gi.invocations.show_invocation(invocation_id)

    # Check for completion
    if 'Results' not in invocation['outputs']:
        return 'error'
    else:
        for output in (history.get_dataset(output['id']) for _, output in invocation['outputs'].items()):
            if output.state in ('error', 'paused'):
                return 'error'
            if output.state != 'ok':
                'running'
        else:
            return 'done'


def _flatten(l):
    data = []
    for datum in l:
        if isinstance(datum, list):
            data.extend(datum)
        else:
            data.append(datum)
    return data


def _retryConnection(f, *args, **kwargs):
    for _ in range(5):
        try:
            return f(*args, **kwargs)
        except (requests.exceptions.ConnectionError, bioblend.ConnectionError, ConnectionError):
            time.sleep(1)
            pass


def main(args: argparse.Namespace):
    """
    Script entrance function
    """
    conn = GalaxyInstance(args.host, args.key)
    if args.command not in ('reference', 'runs', 'results', 'cancel'):
        upload_history = get_upload_history(conn)

    if 'reference_id' in args and args.reference_id:
        # Attempt to recover from user entering accession rather than reference id
        args.reference_id = re.sub('\W', '_', args.reference_id)

    if args.command == 'upload':
        print("Dataset ID:", file=sys.stderr)
        sys.stderr.flush()
        hda = upload(upload_history, args.path, args.label)
        print(hda.id)

    elif args.command == 'list':
        print("ID\tLabel", file=sys.stderr)
        sys.stderr.flush()
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
        sys.stderr.flush()
        for genome in list_reference(conn, args.query):
            print(f"{genome[1]}\t{genome[0]}")

    elif args.command == 'run':
        workflow = get_workflow(conn)
        if args.output and not args.output.is_dir():
            main.cmd.error("Output path must be existing folder")

        # Deal with bug in argparse 'extend' by switching to 'append' and flattening
        data = _flatten(args.data)
        newick = None
        if args.newick_accession or args.newick_label:
            newick = upload_history.get_dataset(args.newick_accession or args.newick_label)
        print("Analysis ID:", file=sys.stderr)
        sys.stderr.flush()
        invocation_id, _ = invoke(workflow, args.label, [upload_history.get_dataset(id) for id in data], newick, 'newick_accession' in args, args.reference_id)
        print(invocation_id)
        if args.output:
            results(workflow, invocation_id, args.output)

    elif args.command == 'runs':
        workflow = get_workflow(conn)
        print("ID\tLabel\tState", file=sys.stderr)
        sys.stderr.flush()
        for invocation in invocations(workflow):
            print(f"{invocation['id']}\t{invocation['label']}\t{invocation['state']}")  # TODO get actual state

    elif args.command == 'download':
        workflow = get_workflow(conn)
        results(workflow, args.id, args.path)

    elif args.command == 'cancel':
        workflow = get_workflow(conn)
        cancel(workflow, args.id)

    elif args.command == 'errors':
        workflow = get_workflow(conn)
        for e in errors(workflow, args.id).values():
            print(e)

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
please use the `./islandcompare.py upload`, `./islandcompare.py run`, and `./islandcompare.py download` commands.

If you are providing your own phylogenetic tree it must be in Newick format.
The Newick dataset can contain identifiers that either refer to the dataset accession or the dataset label.
Keep in mind that dataset labels default to the file name if not provided at upload.
''', epilog='See https://islandcompare.ca/ for a GUI', formatter_class=argparse.RawTextHelpFormatter)
main.cmd.add_argument('--host', type=str, default=os.environ.get('GALAXY_HOST', 'https://galaxy.islandcompare.ca/'), help='Galaxy instance url (GALAXY_HOST environment variable)')
main.cmd.add_argument('--key', type=str, help='API key (GALAXY_API_KEY environment variable). Key for the default host is provided in the instructions on the Analysis page at https://islandcompare.ca/analysis', **({"default": os.environ.get('GALAXY_API_KEY')} if 'GALAXY_API_KEY' in os.environ else {"required": True}))
main.cmd.add_argument('--version', action='version', version=__version__)
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

    for _ in range(5):
        if type:
            hda = _retryConnection(history.upload_file, str(path.resolve()), file_name=label, file_type=type)
        else:
            hda = _retryConnection(history.upload_file, str(path.resolve()), file_name=label)

        return hda

    raise RuntimeError('Failed to upload ' + label)


upload.cmd_help = 'Upload datasets'
upload.cmd = main.subcmds.add_parser('upload', help=upload.cmd_help, description=upload.cmd_help)
upload.cmd.add_argument('path', type=Path, help='Path of dataset to upload')
upload.cmd.add_argument('label', type=str, nargs='?', help='Dataset label. Defaults to file name.')

HDA = namedtuple('HDA', ('id', 'name'))
#list data
def list_data(history: History, type: str = '') -> List[HistoryDatasetAssociation]:
    """
    List the data that was previously uploaded
    :param history: History instance to list
    :param type: Filter on a type of data
    :return: List of history contents
    """
    #return [dataset for dataset in history.get_datasets() if not dataset.deleted and (not type or dataset.file_ext == type)]
    return [HDA(i.id, i.name) for i in history.content_infos if i.deleted is False]


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
    _retryConnection(history.gi.gi.histories.delete_dataset, history.id, id, True)


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
    history = _retryConnection(workflow.gi.histories.create, history_label)

    history.tags.append(workflow.id)
    history.tags.append(application_tag)
    _retryConnection(history.update, tags=history.tags)

    elements = [HistoryDatasetElement(id=datum.id, name=datum.name) for datum in data]

    input_collection = _retryConnection(history.create_dataset_collection, CollectionDescription('input_data', type='list', elements=elements))
    inputs = {
        inputs['Input datasets']: {'id': input_collection.id, 'src': input_collection.SRC},
        inputs['Phylogenetic tree in newick format']: {'id': newick.id, 'src': newick.SRC} if newick else None,
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
    workflow.gi._wait_datasets(data, polling_interval=1, break_on_error=True)
    inputs, history = _prepare_inputs(workflow, label, data, newick, accession, reference_id)
    invocation = _retryConnection(workflow.gi.gi.workflows.invoke_workflow, workflow.id, inputs, history_id=history.id, allow_tool_state_corrections=True)

    return invocation['id'], history


invoke.cmd_flags = ArgumentParser(add_help=False)  # Make reusable arguments for upload_run
invoke.cmd_help = 'Run IslandCompare'
invoke.cmd_flags.add_argument('label', metavar='analysis_label', type=str, help='Analysis label')
invoke.cmd_flags.add_argument('-r', type=str, dest='reference_id', help="Reference ID to align drafts to. See 'reference' command")
invoke.cmd = main.subcmds.add_parser('run', parents=[invoke.cmd_flags], help=invoke.cmd_help, description=invoke.cmd_help)
invoke.cmd.add_argument('data', metavar='ID', type=str, action='append', help=argparse.SUPPRESS)
invoke.cmd.add_argument('data', metavar='ID', type=str, action='append', nargs='+', help='IDs of Genbank or EMBL datasets as returned by the upload or list commands. Minimum of 2')
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
                result.append({'id': invocation['id'], 'state': get_invocation_state(history, invocation.id), 'label': history.name})

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
    :return: Dict of paths of results keyed on label or None if error
    """
    if not path.is_dir():
        results.cmd.error("Output path must be existing folder")

    invocation = workflow.gi.gi.workflows.show_invocation(workflow.id, invocation_id)
    history = workflow.gi.histories.get(invocation['history_id'])

    print("Waiting for results..", file=sys.stderr)
    try:
        while True:
            time.sleep(workflow.POLLING_INTERVAL)
            history.refresh()
            state = get_invocation_state(history, invocation_id)

            if state == 'error':
                raise BlockingWorkflowError("Blocking error detected")

            if state == 'done':
                break

    except BlockingWorkflowError as e:
        print(e, file=sys.stderr)
        return None

    print("Downloading..", file=sys.stderr)
    ret = {}
    for label, output in invocation['outputs'].items():
        dataset = history.get_dataset(output['id'])
        file_path = (path / label).with_suffix('.' + dataset.file_ext).resolve()
        ret[label] = file_path
        _retryConnection(workflow.gi.gi.datasets.download_dataset, output['id'], file_path, False)
        print(file_path)

    return ret


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
        _retryConnection(workflow.gi.gi.workflows.cancel_invocation, workflow.id, invocation_id)
    except bioblend.ConnectionError as e:
        if json.loads(e.body)['err_msg'] != 'Cannot cancel an inactive workflow invocation.':
            raise e

    # Delete output history
    history = workflow.gi.histories.get(invocation['history_id'])
    _retryConnection(history.delete)


cancel.cmd_help = 'Cancel or delete analysis'
cancel.cmd = main.subcmds.add_parser('cancel', help=cancel.cmd_help, description=cancel.cmd_help)
cancel.cmd.add_argument('id', metavar='ID', type=str, help='Analysis ID')


# Get errors
def errors(workflow: Workflow, invocation_id: str):
    """
    Get any errors that may have occurred during the workflow
    :param workflow: Workflow instance
    :param invocation_id: ID of workflow invocation
    :return: Dict of strings containing error messages keyed on job ID
    """
    invocation = workflow.gi.gi.workflows.show_invocation(workflow.id, invocation_id)
    history = workflow.gi.histories.get(invocation['history_id'])

    err = {}
    steps = invocation['steps']
    for step in steps:
        if step['subworkflow_invocation_id']:
            steps.extend(workflow.gi.gi.invocations.show_invocation(step['subworkflow_invocation_id'])['steps'])
            continue
        step = workflow.gi.gi.invocations.show_invocation_step(invocation_id, step['id'])
        label = step['workflow_step_label']
        for job in step['jobs']:
            if job['state'] == 'error':
                job = workflow.gi.jobs.get(job['id'], True).wrapped
                # Resolve input identifier
                input_identifier = list(map(lambda x: job['params'][f"{x}|__identifier__"], filter(lambda x: f"{x}|__identifier__" in job['params'], job['inputs'].keys())))
                if len(input_identifier) == 1: input_identifier = input_identifier[0]
                elif len(input_identifier) > 1: input_identifier = f"[${input_identifier.join(', ')}]"
                else: input_identifier = ''

                err_str = ''
                for key, val in job['outputs'].items():
                    if val['src'] == 'hda':
                        hda = history.get_dataset(val['id'])
                        if hda.state == 'error':
                            err_str += f"{label} on {input_identifier} - {key}: {hda.misc_info}\n"
                    # TODO hdca

                err_str += job['stderr'] + '\n'
                err[job['id']] = err_str
    return err


errors.cmd_help = 'Get any errors during analysis'
errors.cmd = main.subcmds.add_parser('errors', help=errors.cmd_help, description=errors.cmd_help)
errors.cmd.add_argument('id', metavar='ID', type=str, help='Analysis ID')


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
    :return: (Dict of paths of results keyed on label, Dict of strings containing error messages keyed on dataset ID)
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
    print("Analysis ID:", file=sys.stderr)
    print(invocation_id)
    ret = results(workflow, invocation_id, output_path)
    print("Collecting any errors..", file=sys.stderr)
    err = errors(workflow, invocation_id)
    for e in err.values():
        print(e)
    if len(err) == 0:
        print('No errors found', file=sys.stderr)

    print(f"Wall time: {(time.time() - start)/60} minutes", file=sys.stderr)
    print("Cleaning up..", file=sys.stderr)
    _retryConnection(history.delete, purge=True)
    for hda in uploads:
        _retryConnection(hda.delete, purge=True)

    if newick:
        _retryConnection(newick.delete, purge=True)

    return ret, err


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
        print(e, file=sys.stderr)
        traceback.print_exc()
        main.cmd.error(json.loads(e.body)['err_msg'])
