from boto.s3.connection import S3Connection
from boto.s3.key import Key
from datetime import datetime
from fabric.api import env
from fabric.api import execute
from fabric.api import hide
from fabric.api import sudo
from fabric.context_managers import settings
import json
import logging
import time


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

    Snapshots data (and incremental backups) are stored using the following convention:

        s3_bucket_name:/<base_path>/<snapshot_name>/<node-hostname>/...

    Snapshots are represented on S3 by their manifest file, this makes incremental backups
    much easier
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


class BackupWorker(object):
    """
    BackupWorker does the actual snapshot / backup work

    Backup process is split in this steps:
        - requesting cassandra to create new backups
        - uploadint backup files to S3
        - clearing backup files from nodes
        - updating backup meta informations

    When performing a new snapshot the manifest of the snapshot is
    uploaded to S3 for later use.

    Snapshot's manifest path:
    /<snapshot_base_path>/<snapshot_name>/manifest.json

    Everytime a backup is done a description of the current ring is
    saved next to the snapshot manifest file

    """

    connection_pool_size = 12

    def __init__(self, aws_secret_access_key,
                 aws_access_key_id, cassandra_data_path, nodetool_path):
        self.aws_secret_access_key = aws_secret_access_key
        self.aws_access_key_id = aws_access_key_id
        self.cassandra_data_path = cassandra_data_path
        self.nodetool_path = nodetool_path

    def get_current_node_hostname(self):
        return env.host_string

    def upload_backups_to_s3(self, snapshot, files):
        prefix = '/'.join(snapshot.base_path.split(
            '/') + [self.get_current_node_hostname()])
        upload_command = "s3funnel %(bucket)s PUT --put-full-path --threads 4 --add-prefix %(prefix)s --aws_key=%(key)s --aws_secret=%(secret)s %(files)s -v"
        cmd = upload_command % dict(
            bucket=snapshot.s3_bucket,
            prefix=prefix,
            key=self.aws_access_key_id,
            secret=self.aws_secret_access_key,
            files=' '.join("'%s'" % f for f in files)
        )
        sudo(cmd)

    def snapshot(self, snapshot):
        """
        Perform a snapshot
        """
        logging.info('Create %r snapshot' % snapshot)
        try:
            self.start_cluster_backup(snapshot, incremental_backups=False)
            self.upload_cluster_backups(snapshot, incremental_backups=False)
        finally:
            self.clear_cluster_snapshot(snapshot)
        self.write_ring_description(snapshot)
        self.write_snapshot_manifest(snapshot)

    def update_snapshot(self, snapshot):
        """
        Updates backup data changed since :snapshot was done
        """
        logging.info('Update %r snapshot' % snapshot)
        try:
            self.start_cluster_backup(snapshot, incremental_backups=True)
            self.upload_cluster_backups(snapshot, incremental_backups=True)
        finally:
            self.clear_cluster_backups(snapshot)
        self.write_ring_description(snapshot)

    def get_ring_description(self):
        with settings(host_string=env.hosts[0]):
            with hide('output'):
                ring_description = sudo('nodetool ring')
        return ring_description

    def write_on_S3(self, bucket_name, path, content):
        conn = S3Connection(self.aws_access_key_id, self.aws_secret_access_key)
        bucket = conn.get_bucket(bucket_name)
        key = bucket.new_key(path)
        key.set_contents_from_string(content)

    def write_ring_description(self, snapshot):
        content = self.get_ring_description()
        ring_path = '/'.join([snapshot.base_path, 'ring'])
        self.write_on_S3(snapshot.s3_bucket, ring_path, content)

    def write_snapshot_manifest(self, snapshot):
        content = snapshot.dump_manifest_file()
        manifest_path = '/'.join([snapshot.base_path, 'manifest.json'])
        self.write_on_S3(snapshot.s3_bucket, manifest_path, content)

    def start_cluster_backup(self, snapshot, incremental_backups=False):
        logging.info('Creating snapshots')
        with settings(parallel=True, pool_size=self.connection_pool_size):
            execute(self.node_start_backup, snapshot, incremental_backups)

    def node_start_backup(self, snapshot, incremental_backups):
        '''
        runs snapshot command on a cassandra node
        '''

        if snapshot.table:
            table_param = '-cf %s' % snapshot.table
        else:
            table_param = ''

        if incremental_backups:
            backup_command = '%(nodetool)s flush %(keyspaces)s %(table_param)s'
        else:
            backup_command = '%(nodetool)s snapshot -t "%(snapshot)s" %(keyspaces)s %(table_param)s'

        cmd = backup_command % dict(
            nodetool=self.nodetool_path,
            snapshot=snapshot.name,
            keyspaces=snapshot.keyspaces or '',
            table_param=table_param
        )
        sudo(cmd)

    def upload_cluster_backups(self, snapshot, incremental_backups):
        logging.info('Uploading backups')
        with settings(parallel=True, pool_size=self.connection_pool_size):
            execute(self.upload_node_backups, snapshot, incremental_backups)

    def upload_node_backups(self, snapshot, incremental_backups):
        '''
        uploads node backup data to S3
        '''
        files = self.get_node_backup_files(snapshot, incremental_backups)
        if len(files) == 0:
            logging.warning('nothing to backup here')
        else:
            self.upload_backups_to_s3(snapshot, files)

    def get_node_backup_files(self, snapshot, incremental_backups):
        if snapshot.keyspaces:
            keyspace_globs = snapshot.keyspaces.split()
        else:
            keyspace_globs = ['*']

        if snapshot.table:
            table_glob = snapshot.table
        else:
            table_glob = '*'

        files = []
        for keyspace_glob in keyspace_globs:
            path = [
                self.cassandra_data_path,
                keyspace_glob,
                table_glob
            ]
            if incremental_backups:
                path += ['backups']
            else:
                path += ['snapshots', snapshot.name]
            path += ['*']

            with hide('output'):
                path = sudo('python -c "import os; print os.path.join(*%s)"' % path)

            logging.info('list files to backup matching %s path', path)
            with hide('output'):
                glob_results = sudo("python -c \"import glob; print '\\n'.join(glob.glob('%s'))\"" % path)
                files.extend([f.strip() for f in glob_results.split("\n")])
            logging.info("found %d files", len(files))

        return files

    def clear_cluster_snapshot(self, snapshot):
        logging.info('Clearing snapshots')
        with settings(parallel=True, pool_size=self.connection_pool_size):
            execute(self.clear_node_snapshot, snapshot)

    def clear_node_snapshot(self, snapshot):
        '''
        cleans up snapshots from a cassandra node
        '''
        clear_command = '%(nodetool)s clearsnapshot -t "%(snapshot)s"'
        cmd = clear_command % dict(
            nodetool=self.nodetool_path,
            snapshot=snapshot.name
        )
        sudo(cmd)

    def clear_cluster_backups(self, snapshot):
        logging.info('Clearing backup data')
        with settings(parallel=True, pool_size=self.connection_pool_size):
            execute(self.clear_node_backups, snapshot)

    def clear_node_backups(self, snapshot):
        '''
        cleans up backup files from a cassandra node
        '''
        files = self.get_node_backup_files(snapshot, incremental_backups=True)
        for f in files:
            sudo('rm %s' % f)


class SnapshotCollection(object):

    def __init__(self, aws_access_key_id, aws_secret_access_key, base_path, s3_bucket):
        self.s3_bucket = s3_bucket
        self.base_path = base_path
        self.snapshots = None
        self.aws_access_key_id = aws_access_key_id
        self.aws_secret_access_key = aws_secret_access_key

    def _read_s3(self):
        conn = S3Connection(self.aws_access_key_id, self.aws_secret_access_key)
        bucket = conn.get_bucket(self.s3_bucket)
        self.snapshots = []
        prefix = self.base_path
        if not self.base_path.endswith('/'):
            prefix = '%s/' % self.base_path
        snap_paths = [snap.name for snap in bucket.list(
            prefix=prefix, delimiter='/')]
        for snap_path in snap_paths:
            mkey = Key(bucket)
            manifest_path = '/'.join([snap_path, 'manifest.json'])
            mkey.key = manifest_path
            manifest_data = mkey.get_contents_as_string()
            self.snapshots.append(
                Snapshot.load_manifest_file(manifest_data, self.s3_bucket))
        self.snapshots = sorted(self.snapshots, reverse=True)

    def get_snapshot_for(self, hosts, keyspaces, table):
        '''
        returns the most recent compatible snapshot
        '''
        for snapshot in self:
            if snapshot.hosts != hosts:
                continue
            if snapshot.keyspaces != keyspaces:
                continue
            if snapshot.table != table:
                continue
            return snapshot

    def __iter__(self):
        if self.snapshots is None:
            self._read_s3()
        return iter(self.snapshots)
