import argparse
from collections import defaultdict
from fabric.api import env
import logging
from snapshotting import BackupWorker
from snapshotting import Snapshot
from snapshotting import SnapshotCollection


def run_backup(args):
    if args.user:
        env.user = args.user
    env.hosts = sorted(args.hosts.split(','))

    if args.new_snapshot:
        create_snapshot = True
    else:
        existing_snapshot = SnapshotCollection(
            args.aws_access_key_id,
            args.aws_secret_access_key,
            args.s3_base_path,
            args.s3_bucket_name
        ).get_snapshot_for(
            hosts=env.hosts,
            keyspaces=args.keyspaces,
            table=args.table
        )
        create_snapshot = existing_snapshot is None

    worker = BackupWorker(
        aws_access_key_id=args.aws_access_key_id,
        aws_secret_access_key=args.aws_secret_access_key,
        cassandra_data_path=args.cassandra_data_path,
        nodetool_path=args.nodetool_path
    )

    if create_snapshot:
        logging.info('make a new snapshot')
        snapshot = Snapshot(
            base_path=args.s3_base_path,
            s3_bucket=args.s3_bucket_name,
            hosts=env.hosts,
            keyspaces=args.keyspaces,
            table=args.table
        )
        worker.snapshot(snapshot)
    else:
        logging.info('add incrementals to snapshot %s' % existing_snapshot)
        worker.update_snapshot(existing_snapshot)


def list_backups(args):
    snapshots = SnapshotCollection(
        args.aws_access_key_id,
        args.aws_secret_access_key,
        args.s3_base_path,
        args.s3_bucket_name
    )
    path_snapshots = defaultdict(list)

    for snapshot in snapshots:
        base_path = '/'.join(snapshot.base_path.split('/')[:-1])
        path_snapshots[base_path].append(snapshot)

    for path, snapshots in path_snapshots.iteritems():
        print '-----------[%s]-----------' % path
        for snapshot in snapshots:
            print '\t %r hosts:%r keyspaces:%r table:%r' % (snapshot, snapshot.hosts, snapshot.keyspaces, snapshot.table)
        print '------------------------' + '-' * len(path)

def main():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__)

    # common arguments
    parser.add_argument('--aws-access-key-id',
                        required=True,
                        help='public AWS access key.')

    parser.add_argument('--aws-secret-access-key',
                        required=True,
                        help='S3 secret access key.')

    parser.add_argument('--s3-bucket-name',
                        required=True,
                        help='S3 bucket name for backups.')

    parser.add_argument('--s3-base-path',
                        required=True,
                        help='S3 base path for backups.')

    parser.add_argument('-v', '--verbose',
                        action='store_true',
                        help='increase output verbosity')

    subparsers = parser.add_subparsers(title='subcommands',
                                       dest='subcommand')

    subparsers.add_parser('list', help='list existing backups')

    backup_parser = subparsers.add_parser('backup', help='create a snapshot')

    # snapshot / backup arguments
    backup_parser.add_argument('--hosts',
                               required=True,
                               help='The comma separated list of hosts to snapshot')

    backup_parser.add_argument('--keyspaces',
                               default='',
                               help='The keyspaces to backup (omit to backup all)')

    backup_parser.add_argument('--table',
                               default='',
                               help='The table (column family) to backup')

    backup_parser.add_argument('--cassandra-data-path',
                               default='/var/lib/cassandra/data/',
                               help='cassandra data path.')

    backup_parser.add_argument('--nodetool-path',
                               default='/usr/bin/nodetool',
                               help='nodetool path.')

    backup_parser.add_argument('--user',
                               help='the ssh user to loging on nodes')

    backup_parser.add_argument('--new-snapshot',
                               action='store_true',
                               help='create a new snapshot')

    args = parser.parse_args()
    subcommand = args.subcommand

    if args.verbose:
        logging.basicConfig(level=logging.INFO)

    if subcommand == 'backup':
        run_backup(args)
    elif subcommand == 'list':
        list_backups(args)

if __name__ == '__main__':
    main()
