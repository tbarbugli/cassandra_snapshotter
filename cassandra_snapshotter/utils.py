import argparse
import functools

base_parser = argparse.ArgumentParser(
    formatter_class=argparse.RawDescriptionHelpFormatter,
    description=__doc__)

# common arguments
base_parser.add_argument('--aws-access-key-id',
                    required=True,
                    help='public AWS access key.')

base_parser.add_argument('--aws-secret-access-key',
                    required=True,
                    help='S3 secret access key.')

base_parser.add_argument('--s3-bucket-name',
                    required=True,
                    help='S3 bucket name for backups.')

base_parser.add_argument('--s3-base-path',
                    required=True,
                    help='S3 base path for backups.')

base_parser.add_argument('-v', '--verbose',
                    action='store_true',
                    help='increase output verbosity')

def map_wrap(f):
    '''
    fix annoying multiprocessing.imap bug when sending
    *args and **kwargs
    '''
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        return apply(f, *args, **kwargs)
    return wrapper
