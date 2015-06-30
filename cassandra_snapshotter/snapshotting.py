from __future__ import (absolute_import, print_function)

# From system
import os
import re
import sys
import time
import json
import shutil
import logging
from distutils.util import strtobool
from boto.s3.connection import S3Connection
from boto.s3.key import Key
from boto.exception import S3ResponseError
from datetime import datetime
from fabric.api import (env, execute, hide, run, settings, sudo)
from fabric.context_managers import settings
from multiprocessing.dummy import Pool


class Snapshot(object):
    """
    A Snapshot instance keeps the details about a cassandra snapshot

    Multiple snaphosts can be stored in a single S3 bucket

    A Snapshot is best described by:
        - its name (which defaults to the utc time of creation)
        - the list of hostnames the snapshot runs on
        - the list of keyspaces being backed up
        - the keyspace table being backed up
        - the S3 bucket's base path where the snapshot is stored

    Snapshots data (and incremental backups) are stored using the
    following convention:

        s3_bucket_name:/<base_path>/<snapshot_name>/<node-hostname>/...

    Snapshots are represented on S3 by their manifest file, this makes
    incremental backups much easier
    """

    SNAPSHOT_TIMESTAMP_FORMAT = '%Y%m%d%H%M%S'

    def __init__(self, base_path, s3_bucket, hosts, keyspaces, table):
        self.s3_bucket = s3_bucket
        self.name = self.make_snapshot_name()
        self.hosts = hosts
        self.keyspaces = keyspaces
        self.table = table
        self._base_path = base_path

    def dump_manifest_file(self):
        manifest_data = {
            'name': self.name,
            'base_path': self._base_path,
            'hosts': self.hosts,
            'keyspaces': self.keyspaces,
            'table': self.table
        }
        return json.dumps(manifest_data)

    @staticmethod
    def load_manifest_file(data, s3_bucket):
        manifest_data = json.loads(data)
        snapshot = Snapshot(
            base_path=manifest_data['base_path'],
            s3_bucket=s3_bucket,
            hosts=manifest_data['hosts'],
            keyspaces=manifest_data['keyspaces'],
            table=manifest_data['table']
        )
        snapshot.name = manifest_data['name']
        return snapshot

    @property
    def base_path(self):
        return '/'.join([self._base_path, self.name])

    def make_snapshot_name(self):
        return datetime.utcnow().strftime(self.SNAPSHOT_TIMESTAMP_FORMAT)

    def unix_time_name(self):
        dt = datetime.strptime(self.name, self.SNAPSHOT_TIMESTAMP_FORMAT)
        return time.mktime(dt.timetuple()) * 1000

    def __cmp__(self, other):
        return self.unix_time_name() - other.unix_time_name()

    def __repr__(self):
        return self.name

    __str__ = __repr__


class RestoreWorker(object):
    def __init__(self, aws_access_key_id, aws_secret_access_key, snapshot):
        self.aws_secret_access_key = aws_secret_access_key
        self.aws_access_key_id = aws_access_key_id
        self.s3connection = S3Connection(
            aws_access_key_id=self.aws_access_key_id,
            aws_secret_access_key=self.aws_secret_access_key)
        self.snapshot = snapshot
        self.keyspace_table_matcher = None

    def restore(self, keyspace, table, hosts, target_hosts):
        # TODO:
        # 4. sstableloader

        logging.info("Restoring keyspace=%(keyspace)s,\
            table=%(table)s" % dict(keyspace=keyspace, table=table))
        logging.info("From hosts: %(hosts)s to: %(target_hosts)s" % dict(
            hosts=', '.join(hosts), target_hosts=', '.join(target_hosts)))
        if not table:
            table = ".*?"

        bucket = self.s3connection.get_bucket(
            self.snapshot.s3_bucket, validate=False)

        matcher_string = "(%(hosts)s).*/(%(keyspace)s)/(%(table)s)/" % dict(
            hosts='|'.join(hosts), keyspace=keyspace, table=table)
        self.keyspace_table_matcher = re.compile(matcher_string)

        keys = []
        tables = set()

        for k in bucket.list(self.snapshot.base_path):
            r = self.keyspace_table_matcher.search(k.name)
            if not r:
                continue

            tables.add(r.group(3))
            keys.append(k)

        self._delete_old_dir_and_create_new(keyspace, tables)

        total_size = reduce(lambda s, k: s + k.size, keys, 0)

        logging.info("Found %(files_count)d files, with total size \
            of %(size)s." % dict(
                files_count=len(keys),
                size=self._human_size(total_size)))
        print("Found %(files_count)d files, with total size \
            of %(size)s." % dict(
                files_count=len(keys),
                size=self._human_size(total_size)))

        self._download_keys(keys, total_size)

        logging.info("Finished downloading...")

        self._run_sstableloader(keyspace, tables, target_hosts)

    def _delete_old_dir_and_create_new(self, keyspace, tables):
        keyspace_path = "./{!s}".format(keyspace)
        if os.path.exists(keyspace_path) and os.path.isdir(keyspace_path):
            logging.warning("Deleteing directory ({!s})...".format(
                keyspace_path))
            shutil.rmtree(keyspace_path)

        for table in tables:
            path = "./{!s}/{!s}".format(keyspace, table)
            if not os.path.exists(path):
                os.makedirs(path)

    def _download_keys(self, keys, total_size, pool_size=5):
        logging.info("Starting to download...")

        progress_string = ""
        read_bytes = 0

        thread_pool = Pool(pool_size)

        for size in thread_pool.imap(self._download_key, keys):
            old_width = len(progress_string)
            read_bytes += size
            progress_string = "{!s} / {!s} ({:.2f})".format(
                self._human_size(read_bytes),
                self._human_size(total_size),
                (read_bytes/float(total_size))*100.0)
            width = len(progress_string)
            padding = ""
            if width < old_width:
                padding = " "*(width-old_width)
            progress_string = "{!s}{!s}\r".format(progress_string, padding)

            sys.stderr.write(progress_string)

    def _download_key(self, key):
        r = self.keyspace_table_matcher.search(key.name)
        filename = "./{!s}/{!s}/{!s}_{!s}".format(
            r.group(2), r.group(3),
            key.name.split('/')[2], key.name.split('/')[-1])
        key.get_contents_to_filename(filename)

        return key.size

    def _human_size(self, size):
        for x in ['bytes', 'KB', 'MB', 'GB']:
            if size < 1024.0:
                return "{:3.1f}{!s}".format(size, x)
            size /= 1024.0
        return "{:3.1f}{!s}".format(size, 'TB')

    def _run_sstableloader(self, keyspace, tables, target_hosts):
        # TODO: get path to sstableloader
        for table in tables:
            command = 'sstableloader --nodes %(hosts)s -v \
                %(keyspace)s/%(table)s' % dict(
                    hosts=','.join(target_hosts),
                    keyspace=keyspace, table=table)
            logging.info("invoking: {!s}".format(command))

            os.system(command)


class BackupWorker(object):
    """
    Backup process is split in this steps:
        - requests cassandra to create new backups
        - uploads backup files to S3
        - clears backup files from nodes
        - updates backup meta informations

    When performing a new snapshot the manifest of the snapshot is
    uploaded to S3 for later use.

    Snapshot's manifest path:
    /<snapshot_base_path>/<snapshot_name>/manifest.json

    Everytime a backup is done a description of the current ring is
    saved next to the snapshot manifest file

    """

    def __init__(self, aws_secret_access_key,
                 aws_access_key_id, s3_bucket_region, s3_ssenc,
                 s3_connection_host, cassandra_conf_path, use_sudo,
                 nodetool_path, cassandra_bin_dir, backup_schema,
                 buffer_size, connection_pool_size=12):
        self.aws_secret_access_key = aws_secret_access_key
        self.aws_access_key_id = aws_access_key_id
        self.s3_bucket_region = s3_bucket_region
        self.s3_ssenc = s3_ssenc
        self.s3_connection_host = s3_connection_host
        self.cassandra_conf_path = cassandra_conf_path
        self.nodetool_path = nodetool_path or \
            "{!s}/nodetool".format(cassandra_bin_dir)
        self.cassandra_cli_path = "{!s}/cassandra-cli".format(cassandra_bin_dir)
        self.backup_schema = backup_schema
        self.connection_pool_size = connection_pool_size
        self.buffer_size = buffer_size
        if isinstance(use_sudo, basestring):
            self.use_sudo = bool(strtobool(use_sudo))
        else:
            self.use_sudo = use_sudo

    def get_current_node_hostname(self):
        return env.host_string

    def upload_node_backups(self, snapshot, incremental_backups):
        prefix = '/'.join(snapshot.base_path.split(
            '/') + [self.get_current_node_hostname()])

        manifest_path = '/tmp/backupmanifest'
        manifest_command = "cassandra-snapshotter-agent \
            %(incremental_backups)s create-upload-manifest \
            --manifest_path=%(manifest_path)s \
            --snapshot_name=%(snapshot_name)s \
            --snapshot_keyspaces=%(snapshot_keyspaces)s \
            --snapshot_table=%(snapshot_table)s \
            --conf_path=%(conf_path)s"
        cmd = manifest_command % dict(
            manifest_path=manifest_path,
            snapshot_name=snapshot.name,
            snapshot_keyspaces=snapshot.keyspaces,
            snapshot_table=snapshot.table,
            conf_path=self.cassandra_conf_path,
            incremental_backups=incremental_backups and\
                '--incremental_backups' or ''
        )
        if self.use_sudo:
            sudo(cmd)
        else:
            run(cmd)

        upload_command = "cassandra-snapshotter-agent %(incremental_backups)s \
            put \
            --aws-access-key-id=%(key)s \
            --aws-secret-access-key=%(secret)s \
            --s3-bucket-name=%(bucket)s \
            --s3-bucket-region=%(s3_bucket_region)s %(s3_ssenc)s \
            --s3-base-path=%(prefix)s \
            --manifest=%(manifest)s \
            --bufsize=%(bufsize)s \
            --concurrency=4"
        cmd = upload_command % dict(
            bucket=snapshot.s3_bucket,
            s3_bucket_region=self.s3_bucket_region,
            s3_ssenc=self.s3_ssenc and '--s3-ssenc' or '',
            prefix=prefix,
            key=self.aws_access_key_id,
            secret=self.aws_secret_access_key,
            manifest=manifest_path,
            bufsize=self.buffer_size,
            incremental_backups=incremental_backups and\
                '--incremental_backups' or ''
        )
        if self.use_sudo:
            sudo(cmd)
        else:
            run(cmd)

    def snapshot(self, snapshot):
        """
        Perform a snapshot
        """
        logging.info("Create {!r} snapshot".format(snapshot))
        try:
            self.start_cluster_backup(snapshot, incremental_backups=False)
            self.upload_cluster_backups(snapshot, incremental_backups=False)
        finally:
            self.clear_cluster_snapshot(snapshot)
        self.write_ring_description(snapshot)
        self.write_snapshot_manifest(snapshot)
        if self.backup_schema:
            self.write_schema(snapshot)

    def update_snapshot(self, snapshot):
        """Updates backup data changed since :snapshot was done"""
        logging.info("Update {!r} snapshot".format(snapshot))
        self.start_cluster_backup(snapshot, incremental_backups=True)
        self.upload_cluster_backups(snapshot, incremental_backups=True)
        self.write_ring_description(snapshot)
        if self.backup_schema:
            self.write_schema(snapshot)

    def get_ring_description(self):
        with settings(host_string=env.hosts[0]):
            with hide('output'):
                if self.use_sudo:
                    ring_description = sudo(self.nodetool_path + ' ring')
                else:
                    ring_description = run(self.nodetool_path + ' ring')
        return ring_description

    def get_keyspace_schema(self, keyspace=None):
        output = ""
        with settings(host_string=env.hosts[0]):
            with hide('output'):
                cmd = "echo -e 'show schema;\n' | {!s}".format(
                    self.cassandra_cli_path)
                if keyspace:
                    cmd = "echo -e 'show schema;\n' | {!s} -k {!s}".format(
                        self.cassandra_cli_path, keyspace)
                if self.use_sudo:
                    output = sudo(cmd)
                else:
                    output = run(cmd)
        schema = '\n'.join([l for l in output.split("\n") if re.match(
            r'(create|use| )', l)])
        return schema

    def write_on_S3(self, bucket_name, path, content):
        conn = S3Connection(
            self.aws_access_key_id,
            self.aws_secret_access_key,
            host=self.s3_connection_host)
        bucket = conn.get_bucket(bucket_name, validate=False)
        key = bucket.new_key(path)
        key.set_contents_from_string(content)

    def write_ring_description(self, snapshot):
        logging.info("Writing ring description")
        content = self.get_ring_description()
        ring_path = '/'.join([snapshot.base_path, 'ring'])
        self.write_on_S3(snapshot.s3_bucket, ring_path, content)

    def write_schema(self, snapshot):
        if snapshot.keyspaces:
            for ks in snapshot.keyspaces.split(','):
                logging.info("Writing schema for keyspace {!s}".format(ks))
                content = self.get_keyspace_schema(ks)
                schema_path = '/'.join(
                    [snapshot.base_path, "schema_{!s}.cdl".format(ks)])
                self.write_on_S3(snapshot.s3_bucket, schema_path, content)
        else:
            logging.info("Writing schema for all keyspaces")
            content = self.get_keyspace_schema()
            schema_path = '/'.join([snapshot.base_path, "schema.cdl"])
            self.write_on_S3(snapshot.s3_bucket, schema_path, content)

    def write_snapshot_manifest(self, snapshot):
        content = snapshot.dump_manifest_file()
        manifest_path = '/'.join([snapshot.base_path, 'manifest.json'])
        self.write_on_S3(snapshot.s3_bucket, manifest_path, content)

    def start_cluster_backup(self, snapshot, incremental_backups=False):
        logging.info("Creating snapshots")
        with settings(parallel=True, pool_size=self.connection_pool_size):
            execute(self.node_start_backup, snapshot, incremental_backups)

    def node_start_backup(self, snapshot, incremental_backups):
        """Runs snapshot command on a cassandra node"""

        if snapshot.table:
            table_param = "-cf {!s}".format(snapshot.table)
        else:
            table_param = ''

        if incremental_backups:
            backup_command = "%(nodetool)s flush %(keyspaces)s %(table_param)s"
        else:
            backup_command = "%(nodetool)s snapshot -t %(snapshot)s \
                %(keyspaces)s %(table_param)s"

        cmd = backup_command % dict(
            nodetool=self.nodetool_path,
            snapshot=snapshot.name,
            keyspaces=snapshot.keyspaces or '',
            table_param=table_param
        )

        with hide('running', 'stdout', 'stderr'):
            if self.use_sudo:
                sudo(cmd)
            else:
                run(cmd)

    def upload_cluster_backups(self, snapshot, incremental_backups):
        logging.info("Uploading backups")
        with settings(parallel=True, pool_size=self.connection_pool_size):
            execute(self.upload_node_backups, snapshot, incremental_backups)

    def clear_cluster_snapshot(self, snapshot):
        logging.info("Clearing snapshots")
        with settings(parallel=True, pool_size=self.connection_pool_size):
            execute(self.clear_node_snapshot, snapshot)

    def clear_node_snapshot(self, snapshot):
        """Cleans up snapshots from a cassandra node"""
        clear_command = '%(nodetool)s clearsnapshot -t "%(snapshot)s"'
        cmd = clear_command % dict(
            nodetool=self.nodetool_path,
            snapshot=snapshot.name
        )
        if self.use_sudo:
            sudo(cmd)
        else:
            run(cmd)


class SnapshotCollection(object):

    def __init__(
            self, aws_access_key_id,
            aws_secret_access_key, base_path, s3_bucket):
        self.s3_bucket = s3_bucket
        self.base_path = base_path
        self.snapshots = None
        self.aws_access_key_id = aws_access_key_id
        self.aws_secret_access_key = aws_secret_access_key

    def _read_s3(self):
        if self.snapshots:
            return

        conn = S3Connection(self.aws_access_key_id, self.aws_secret_access_key)
        bucket = conn.get_bucket(self.s3_bucket, validate=False)
        self.snapshots = []
        prefix = self.base_path
        if not self.base_path.endswith('/'):
            prefix = "{!s}/".format(self.base_path)
        snap_paths = [snap.name for snap in bucket.list(
            prefix=prefix, delimiter='/')]
        # Remove the root dir from the list since it won't have a manifest file.
        snap_paths = [x for x in snap_paths if x != prefix]
        for snap_path in snap_paths:
            mkey = Key(bucket)
            manifest_path = '/'.join([snap_path, 'manifest.json'])
            mkey.key = manifest_path
            try:
                manifest_data = mkey.get_contents_as_string()
            except S3ResponseError as e:  # manifest.json not found.
                logging.warn("Response: {!r} manifest_path: {!r}".format(
                    e.message, manifest_path))
                continue
            try:
                self.snapshots.append(
                    Snapshot.load_manifest_file(manifest_data, self.s3_bucket))
            except Exception as e:  # Invalid json format.
                logging.error("Parsing manifest.json failed. {!r}".format(
                    e.message))
                continue
        self.snapshots = sorted(self.snapshots, reverse=True)

    def get_snapshot_by_name(self, name):
        snapshots = filter(lambda s: s.name == name, self)
        return snapshots and snapshots[0]

    def get_latest(self):
        self._read_s3()
        return self.snapshots[0]

    def get_snapshot_for(self, hosts, keyspaces, table):
        """Returns the most recent compatible snapshot"""
        for snapshot in self:
            if snapshot.hosts != hosts:
                continue
            if snapshot.keyspaces != keyspaces:
                continue
            if snapshot.table != table:
                continue
            return snapshot

    def __iter__(self):
        self._read_s3()
        return iter(self.snapshots)
