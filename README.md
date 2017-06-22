cassandra_snapshotter
======================

A tool to backup cassandra nodes using snapshots and incremental backups on S3

The scope of this project is to make it easier to backup a cluster to S3 and to combine
snapshots and incremental backups.

[![Build Status](https://travis-ci.org/tbarbugli/cassandra_snapshotter.svg?branch=master)](https://travis-ci.org/tbarbugli/cassandra_snapshotter) 

How to install
--------------

Both the machine that runs the backup and the Cassandra nodes need to install the tool

``` bash
pip install cassandra_snapshotter
```

Nodes in the cluster also need to have lzop installed so that backups on S3 can be archived compressed

You can install it on Debian/Ubuntu via apt-get

``` bash
apt-get install lzop
```

Make sure you have JNA enabled and (if you want to use them) that incremental backups are enabled in your cassandra config file.


Usage
-----

You can see the list of parameters available via `cassandra-snapshotter --help`

If you want to make `cassandra-snapshotter` more chatty just add `--verbose`.

#### Create a new backup for *mycluster*:


``` bash
cassandra-snapshotter --s3-bucket-name=Z \
                      --s3-bucket-region=eu-west-1 \
                      --s3-base-path=mycluster \
                      --aws-access-key-id=X \ # optional
                      --aws-secret-access-key=Y \ # optional
                      --s3-ssenc \ # optional
                      --verbose \ # optional
                      backup \
                      --hosts=h1,h2,h3,h4 \
                      --user=cassandra # optional
```


- connects via ssh to hosts h1,h2,h3,h4 using user cassandra
- backups up (using snapshots or incremental backups) on the S3 bucket Z
- backups are stored in /mycluster/
- if your bucket is not on us-east-1 region (the default region), you should really specify the region in the command line; otherwise weird 'connection reset by peer' errors can appear as you'll be transferring files amongst regions
- ```--aws-access-key-id``` and ```--aws-secret-access-key``` are optional. Omitting them will use the instance IAM profile. See http://docs.pythonboto.org/en/latest/boto_config_tut.html for more details.
- if you wish to use AWS S3 server-side encryption specify ```--s3-ssenc```


#### List existing backups for *mycluster*:

``` bash
cassandra-snapshotter --s3-bucket-name=Z \
                      --s3-bucket-region=eu-west-1 \
                      --s3-base-path=mycluster \
                      --aws-access-key-id=X \ # optional
                      --aws-secret-access-key=Y \ # optional
                      --s3-ssenc \ # optional
                      list
```


### How it works

cassandra_snapshotter connects to your cassandra nodes using ssh and uses nodetool to generate
the backups for keyspaces / table you want to backup.

Backups are stored on S3 using this convention:


#### Snapshots:

	/s3_base_path/snapshot_creation_time/hostname/cassandra/data/path/keyspace/table/snapshots


#### Incremental Backups:

	/s3_base_path/snapshot_creation_time/hostname/cassandra/data/path/keyspace/table/backups


### S3_BASE_PATH

This parameter is used to make it possible to use for a single S3 bucket to store multiple cassandra backups.

This parameter can be also seen as a backup profile identifier; the snapshotter uses the s3_base_path to search for existing snapshots on your S3 bucket.


### INCREMENTAL BACKUPS

Incremental backups are created only when a snapshot already exists, incremental backups are stored in their parent snapshot path.

incremental_backups are only used when all this conditions are met:

- there is a snapshot in the same base_path
- the existing snapshot was created for the same list of nodes
- the existing snapshot was created with the same keyspace / table parameters

if one of this condition is not met a new snapshot will be created.

In order to take advantage of incremental backups you need to configure your cassandra cluster for it (see cassandra.yaml config file).

__NOTE:__ Incremental backups are not enabled by default on cassandra.


### CREATE NEW SNAPSHOT

If you dont want to use incremental backups, or if for some reason you want to create a new snapshot for your data, run the cassandra_snapshotter with the `--new-snapshot` argument.


### Data retention / Cleanup old snapshots

Its not in the scope of this project to clean up your S3 buckets.
S3 Lifecycle rules allows you do drop or archive to Glacier object stored based on their age.

### Restore your data

There are two types of restore:
 * using `sstableloader` (manual or automatic)
 * local restore: download data on the local server

#### sstableloader (automatic)

Mandatory parameters:

 * `--target-hosts TARGET_HOSTS`: the comma separated list of hosts to restore into. These hosts will received data from sstableloader.
 * `--keyspace KEYSPACE`: the keyspace to restore.

Optional parameters:

 * `--hosts`: comma separated list of hosts to restore from; leave empty for all
 * `--table TABLE`: the table (column family) to restore; leave blank for all
 * `--restore-dir`: where to download files from S3 before to stream them. Default: `/tmp/restore_cassandra/`
 * `--snapshot-name SNAPSHOT_NAME`: the name of the snapshot to restore

Example to restore `Keyspace1` on `10.0.100.77` with data fetched from a two nodes backup:

``` bash
cassandra-snapshotter --s3-bucket-name=Z \
                      --s3-bucket-region=eu-west-1 \
                      --s3-base-path=mycluster \
                      --aws-access-key-id=X \ # optional
                      --aws-secret-access-key=Y \ # optional
                      restore \
                      --hosts=10.0.2.68,10.0.2.67 \ # optional
                      --target-hosts=10.0.100.77 \ # where to restore data
                      --keyspace Keyspace1 \
                      --snapshot-name 20160614202644 \ # optional
                      --restore-dir /tmp/cassandra_restore/ # optional
```

Make sure there is enough free disk space on the `--restore-dir` filesystem.

#### sstableloader (manual)

If you want to restore files without loading them via `sstableloader` automatically, you can use the `--no-sstableloader` option.
Data will just be downloaded. Use it if you want to do some checks and then run sstableloader manually.

The files are saved following this format:

``` bash
<--restore-dir>/<--keyspace>/<--table>/<HOST>_<filename>
```

Example:

``` bash
/tmp/cassandra_restore/Keyspace1/Standard1/10.0.53.68_Keyspace1-Standard1-jb-1-Data.db
```

Again, make sure there is enough free disk space on the `--restore-dir` filesystem.

#### Local restore

If you have lots of data you probably don't want to download data on a server and then stream these data with `sstableloader` on another one server.
The `--local` option allows you to restore data directly on the local server where the command is run. Note this procedure allows to restore only one host,
so if you want to restore several nodes you have a to run this command on each server.

On production, do not restore directly on the C* data directory (e.g. --restore-dir /var/lib/cassandra/data/ ) it's safer to restore on a different location.
Then make some checks (Number of files seems good? The total size seems correct? Files are uncompressed? What about file permissions?) and if all is OK just `mv` the data.
To make the `mv` command fast, just download data on the same filesystem.
Also prior to run the command ensure that the filesystem can host the data (enough free disk space).

Example:

Let's say we have a filesystem mounted on `/cassandra`.
We want to download files on `/cassandra/restore/` (no need to create the `restore` directory, `cassandra_snapshotter` will create it).

The following command will restore from `10.0.2.68` on the local server into `/cassandra/restore/`:

``` bash
cassandra-snapshotter --s3-bucket-name=Z \
                      --s3-bucket-region=eu-west-1 \
                      --s3-base-path=mycluster \
                      --aws-access-key-id=X \ # optional
                      --aws-secret-access-key=Y \ # optional
                      --verbose \
                      restore \
                      --hosts=10.0.2.68 \ # select the source host. Only one node is allowed in local restore.
                      --snapshot-name 20160614202644 \ # optional
                      --restore-dir /cassandra/restore/ \ #
                      --keyspace Keyspace1 \
                      --local
```

The files are saved following this format:

``` bash
<--restore-dir>/<--keyspace>/<--table>/<filename>
```

Note the filenames are *not* prefixed by `<HOST>_` because we restore from only one node in this mode, so it would be useless.

Example:

``` bash
/tmp/cassandra_restore/Keyspace1/Standard1/Keyspace1-Standard1-jb-1-Data.db
```

Here are the DataStax procedures to follow when using a local restore:
 * Cassandra v2.0: https://docs.datastax.com/en/cassandra/2.0/cassandra/operations/ops_backup_snapshot_restore_t.html
 * Cassandra v2.1: https://docs.datastax.com/en/cassandra/2.1/cassandra/operations/ops_backup_snapshot_restore_t.html
 * Cassandra v2.2: http://docs.datastax.com/en/cassandra/2.2/cassandra/operations/opsBackupSnapshotRestore.html
 * Cassandra v3.x: http://docs.datastax.com/en/cassandra/3.x/cassandra/operations/opsBackupSnapshotRestore.html

### Ring information

In case you need, cassandra_snapshotter stores the ring token description every time a backup is done.

You can find it in the `ring` file in the snapshot base path, for instance:

```
/test-cassandra-snapshots/cassandrasnapshots/20160614202644/ring
```

[![Bitdeli Badge](https://d2weczhvl823v0.cloudfront.net/tbarbugli/cassandra_snapshotter/trend.png)](https://bitdeli.com/free "Bitdeli Badge")
