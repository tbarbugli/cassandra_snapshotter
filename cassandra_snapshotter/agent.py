from boto.s3.connection import S3Connection
try:
    from cStringIO import StringIO
except ImportError:
    from StringIO import StringIO
import subprocess
import multiprocessing
import logging
import os
import glob
from utils import add_s3_arguments
from utils import base_parser
from utils import map_wrap
from tempfile import NamedTemporaryFile


BUFFER_SIZE = 62914560 # 60MB
LZOP_BIN = 'lzop'
DEFAULT_CONCURRENCY = max(multiprocessing.cpu_count() - 1, 1)

logger = logging.getLogger(__name__)


def check_lzop():
    try:
        subprocess.call([LZOP_BIN, '--version'])
    except OSError:
        print "%s not found on path" % LZOP_BIN


def compressed_pipe(path):
    """
    returns a generator that yields compressed chunks of
    the given file_path

    compression is done with lzop

    """
    lzop = subprocess.Popen(
        (LZOP_BIN, '--stdout', path),
        bufsize=BUFFER_SIZE,
        stdout=subprocess.PIPE
    )

    while True:
        chunk = lzop.stdout.read(BUFFER_SIZE)
        if not chunk: break
        yield StringIO(chunk)

def get_bucket(s3_bucket, aws_access_key_id, aws_secret_access_key):
    connection = S3Connection(
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key
    )
    return connection.get_bucket(s3_bucket)

def destination_path(s3_base_path, file_path, compressed=True):
    suffix = compressed and '.lzo' or ''
    return '/'.join([s3_base_path, file_path + suffix])

@map_wrap
def upload_file(bucket, source, destination):
    mp = bucket.initiate_multipart_upload(destination)
    try:
        for i, chunk in enumerate(compressed_pipe(source)):
            mp.upload_part_from_file(chunk, i+1)
    except:
        mp.cancel_upload()
        raise
    mp.complete_upload()

def put_from_manifest(s3_bucket, s3_base_path, aws_access_key_id, aws_secret_access_key, manifest, concurrency=None):
    '''
    uploads files listed in a manifest to amazon S3
    to support larger than 5GB files multipart upload is used (chunks of 60MB)
    files are uploaded compressed with lzop, the .lzo suffix is appended to the file name

    '''
    bucket = get_bucket(s3_bucket, aws_access_key_id, aws_secret_access_key)
    manifest_fp = open(manifest, 'r')
    files = manifest_fp.read().splitlines()
    pool = multiprocessing.Pool(concurrency)
    for _ in pool.imap(upload_file, ((bucket, f, destination_path(s3_base_path, f)) for f in files)):
        pass
    pool.terminate()


def create_upload_manifest(snapshot_name, snapshot_keyspaces, snapshot_table, data_path, manifest_path, incremental_backups=False):
    if snapshot_keyspaces:
        keyspace_globs = snapshot_keyspaces.split()
    else:
        keyspace_globs = ['*']

    if snapshot_table:
        table_glob = snapshot_table
    else:
        table_glob = '*'

    files = []
    for keyspace_glob in keyspace_globs:
        path = [
            data_path,
            keyspace_glob,
            table_glob
        ]
        if incremental_backups:
            path += ['backups']
        else:
            path += ['snapshots', snapshot_name]
        path += ['*']

        os.path.join('*' % path)

        glob_results = '\n'.join(glob.glob(path))
        files.extend([f.strip() for f in glob_results.split("\n")])

    with open(manifest_path, 'w') as manifest:
        manifest.write('\n'.join("%s" % f for f in files))


def main():
    subparsers = base_parser.add_subparsers(title='subcommands',
                                       dest='subcommand')
    put_parser = subparsers.add_parser('put', help='put files on s3 from a manifest')
    manifest_parser = subparsers.add_parser('create-backup-manifest', help='put files on s3 from a manifest')

    # put arguments
    put_parser = add_s3_arguments(put_parser)
    put_parser.add_argument('--manifest',
                           required=True,
                           help='The manifest containing the files to put on s3')

    put_parser.add_argument('--concurrency',
                           required=False,
                           default=DEFAULT_CONCURRENCY,
                           type=int,
                           help='Compress and upload concurrent processes')

    # create-backup-manifest arguments
    manifest_parser.add_argument('--snapshot_name', required=True, type=str)
    manifest_parser.add_argument('--snapshot_keyspaces', default='', required=False, type=str)
    manifest_parser.add_argument('--snapshot_table', required=False, default='', type=str)
    manifest_parser.add_argument('--data_path', required=True, type=str)
    manifest_parser.add_argument('--incremental_backups', default=False, required=False, type=bool)
    manifest_parser.add_argument('--manifest_path', required=True, type=str)

    args = base_parser.parse_args()
    subcommand = args.subcommand

    check_lzop()

    if subcommand == 'create-upload-manifest':
        create_upload_manifest(
            args.snapshot_name,
            args.snapshot_keyspaces,
            args.snapshot_table,
            args.data_path,
            args.incremental_backups,
        )

    if subcommand == 'put':
        put_from_manifest(
            args.s3_bucket_name,
            args.s3_base_path,
            args.aws_access_key_id,
            args.aws_secret_access_key,
            args.manifest,
            args.concurrency
        )

if __name__ == '__main__':
    main()

