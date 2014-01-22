from boto.s3.connection import S3Connection
try:
    from cStringIO import StringIO
except ImportError:
    from StringIO import StringIO
import subprocess
import multiprocessing
import logging
from utils import base_parser
from utils import map_wrap


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

def main():
    subparsers = base_parser.add_subparsers(title='subcommands',
                                       dest='subcommand')
    put_parser = subparsers.add_parser('put', help='put files on s3 from a manifest')

    # put arguments
    put_parser.add_argument('--manifest',
                           required=True,
                           help='The manifest containing the files to put on s3')

    put_parser.add_argument('--concurrency',
                           required=False,
                           default=DEFAULT_CONCURRENCY,
                           type=int,
                           help='Compress and upload concurrent processes')

    args = base_parser.parse_args()
    subcommand = args.subcommand

    check_lzop()

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

