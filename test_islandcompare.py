#!/usr/bin/env python3
import shutil
import tempfile
from pathlib import Path
from unittest import TestCase

from bioblend.galaxy.objects import GalaxyInstance, Workflow, History

import islandcompare as cli


class TestBase(TestCase):
    host = 'https://galaxy.islandcompare.ca'
    key = 'ada87d7d689a4db602341b898c2e3c2e'
    cmd_args = ['--host', host, '--key', key]

    def setUp(self) -> None:
        super().setUp()
        self.conn = GalaxyInstance(self.host, self.key)

    def tearDown(self) -> None:
        super().tearDown()

        # delete all histories
        for history in self.conn.histories.list():
            history.delete(purge=True)


class TestResources(TestBase):
    def test_get_workflow(self):
        workflow = cli.get_workflow(self.conn)
        self.assertIsInstance(workflow, Workflow, "Workflow object not returned")
        self.assertIsNotNone(workflow.gi, "Workflow object returned does not have attached connection")
        self.assertEqual(workflow.name, cli.workflow_name, "Unexpected workflow name")

    def test_get_upload_history(self):
        history = cli.get_upload_history(self.conn)
        self.assertIsInstance(history, History, "History object not returned")
        self.assertIsNotNone(history.gi, "History object returned does not have attached connection")
        self.assertEqual(history.name, cli.upload_history_name, "Unexpected upload history name")
        self.assertIn(cli.upload_history_tag, history.tags, "Unexpected upload history name")
        self.assertFalse(history.deleted, "History is deleted")

    def test_list_reference(self):
        genomes = cli.list_reference(self.conn)
        self.assertGreater(len(genomes), 0)
        filtered_genomes = cli.list_reference(self.conn, 'kleb')
        self.assertGreater(len(genomes), len(filtered_genomes))


class TestWithData(TestBase):
    data = [Path('./data/15584_genome.gbk'), Path('./data/Run4--Set4bH2.gbk')]

    def setUp(self) -> None:
        super().setUp()

        # Ensure data exists
        for datum in self.data:
            self.assertTrue(datum.is_file(), "Test data not found: " + str(datum))

        self.upload_history = cli.get_upload_history(self.conn)
        if len(self.upload_history.get_datasets()):
            # History isn't fresh, delete and recreate
            self.upload_history.delete(purge=True)
            self.upload_history = cli.get_upload_history(self.conn)

    def tearDown(self) -> None:
        super().tearDown()


class TestUpload(TestWithData):
    def test_upload(self):
        upload = cli.upload(self.upload_history, self.data[0])
        self.assertEqual(upload.name, self.data[0].name)
        self.assertFalse(upload.deleted, "Dataset is deleted")

    def test_upload_label(self):
        upload = cli.upload(self.upload_history, self.data[0], 'test')
        self.assertEqual('test', upload.name)
        self.assertFalse(upload.deleted, "Dataset is deleted")

    def test_upload_cmd(self):
        cli.main(cli.main.cmd.parse_args([*self.cmd_args, 'upload', str(self.data[0]), 'test']))
        self.upload_history.refresh()
        data = cli.list_data(self.upload_history)
        self.assertEqual(1, len(data))
        self.assertEqual('test', data[0].name)


class TestWithDatasets(TestWithData):
    def setUp(self) -> None:
        super().setUp()
        self.datasets = [cli.upload(self.upload_history, data) for data in self.data]


class TestUploaded(TestWithDatasets):
    def test_list_data(self):
        data = cli.list_data(self.upload_history)
        self.assertEqual(len(data), len(self.data))
        for datum, path in zip(data, self.data):
            self.assertEqual(datum.name, path.name)

    def test_delete_data(self):
        data = cli.list_data(self.upload_history)
        cli.delete_data(self.upload_history, data[0].id)
        new_data = cli.list_data(self.upload_history)
        self.assertEqual(len(data)-1, len(new_data))
        self.assertEqual(data[1].id, new_data[0].id)


class TestWithWorkflow(TestWithDatasets):
    expected_outputs = {'Results.gff3', 'Genomic Islands.gff3', 'Newick.newick'}

    def setUp(self) -> None:
        super().setUp()
        self.workflow = cli.get_workflow(self.conn)
        self.invocation_id = None
        self.output_path = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        super().tearDown()
        if self.invocation_id:
            cli.cancel(self.workflow, self.invocation_id)
        shutil.rmtree(self.output_path)


class TestInvoke(TestWithWorkflow):
    def test_invoke_basic(self):
        try:
            self.invocation_id, _ = cli.invoke(self.workflow, 'basic', self.datasets)
        except Exception as e:
            self.fail("Failed to invoke workflow: " + str(e))

        try:
            invocation = self.conn.gi.workflows.show_invocation(self.workflow.id, self.invocation_id)
        except Exception as e:
            self.fail("Failed to find invocation")

        try:
            history = self.conn.histories.get(invocation['history_id'])
        except Exception as e:
            self.fail("Failed to find invocation history")

        self.assertNotIn(invocation['state'], ('error', 'cancelled'))

    # TODO test invoke w. reference_id
    # TODO test_invoke_newick accession
    # TODO test_invoke_newick file name

    def test_round_trip(self):
        cli.round_trip(self.upload_history, self.data, self.workflow, 'test', self.output_path)
        outputs = {path.name for path in self.output_path.glob('*')}
        self.assertTrue(self.expected_outputs.issubset(outputs))

    def test_round_trip_cmd(self):
        cli.main(cli.main.cmd.parse_args([*self.cmd_args, 'upload_run', 'test', *[str(datum) for datum in self.data], str(self.output_path)]))
        outputs = {path.name for path in self.output_path.glob('*')}
        self.assertTrue(self.expected_outputs.issubset(outputs))


class TestWithInvocation(TestWithWorkflow):
    def setUp(self) -> None:
        super().setUp()
        self.invocation_id, _ = cli.invoke(self.workflow, 'test', self.datasets)


class TestInvocation(TestWithInvocation):
    def test_invocations(self):
        invocations = cli.invocations(self.workflow)
        self.assertIn(self.invocation_id, [invocation['id'] for invocation in invocations])

    def test_results(self):
        cli.results(self.workflow, self.invocation_id, self.output_path)
        outputs = {path.name for path in self.output_path.glob('*')}
        self.assertTrue(self.expected_outputs.issubset(outputs))

    def test_cancel(self):
        cli.cancel(self.workflow, self.invocation_id)
        invocation = self.conn.gi.workflows.show_invocation(self.workflow.id, self.invocation_id)
        history = self.conn.histories.get(invocation['history_id'])
        self.assertEqual(invocation['state'], 'cancelled')
        self.assertTrue(history.deleted)
