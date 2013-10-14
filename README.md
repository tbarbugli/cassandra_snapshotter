cassandra_snapshotter
======================

A tool to backup cassandra nodes using snapshots and incremental backups on S3

The scope of this project is to make it easier to backup a cluster to S3 and to combine
snapshots and incremental backups.

How to install
--------------

On your worker machine (the machines that runs cassandra_cluster)

``` bash
pip install cassandra_snapshotter`
```

On your cluster nodes:

``` bash
pip install s3funnel
```

Make sure you have JNA enabled and (if you want to use them) that incremental backups are enabled in your cassandra config file.

Usage
-----

You can see the list of parameters available via `cassandra-snapshotter --help`

####Create a new backup for *mycluster*:####


``` bash
cassandra-snapshotter --aws-access-key-id=X --aws-secret-access-key=Y --s3-bucket-name=Z --s3-base-path=mycluster backup --hosts=h1,h2,h3,h4 --user=cassandra
```


- connects via ssh to hosts h1,h2,h3,h4 using user cassandra
- backups up (using snapshots or incremental backups) on the S3 bucket Z
- backups are stored in /mycluster/


####List existing backups for *mycluster*:####

``` bash
cassandra-snapshotter --aws-access-key-id=X --aws-secret-access-key=Y --s3-bucket-name=Z --s3-base-path=mycluster list
```

###How it works###

cassandra_snapshotter connects to your cassandra nodes using ssh and uses nodetool to generate
the backups for keyspaces / table you want to backup.

Backups are stored on S3 using this convention:

####Snapshots:####

	s3_bucket_name/s3_base_path/snapshot_creation_time/hostname/cassandra/data/path/keyspace/table/snapshots

####Incremental Backups:####

	s3_bucket_name/s3_base_path/snapshot_creation_time/hostname/cassandra/data/path/keyspace/table/backups

###S3_BASE_PATH###

This parameter is used to make it possible to use for a single S3 bucket to store multiple cassandra backups.

This parameter can be also seen as a backup profile identifier; the snapshotter uses the s3_base_path to search for existing snapshots on your S3 bucket.


###INCREMENTAL BACKUPS###

Incremental backups are created only when a snapshot already exists, incremental backups are stored in their parent snapshot path.

incremental_backups are only used when all this conditions are met:

- there is a snapshot in the same base_path
- the existing snapshot was created for the same list of nodes
- the existing snapshot was created with the same keyspace / table parameters

if one of this condition is not met a new snapshot will be created.

In order to take advantage of incremental backups you need to configure your cassandra cluster for it (see cassandra.yaml config file).

__NOTE:__ Incremental backups are not enabled by default on cassandra.


###CREATE NEW SNAPSHOT###

If you dont want to use incremental backups, or if for some reason you want to create a new snapshot for your data, run the cassandra_snapshotter with the `--new-snapshot` argument.

###Data retention / Cleanup old snapshots###

Its not in the scope of this project to clean up your S3 buckets.   
S3 Lifecycle rules allows you do drop or archive to Glacier object stored based on their age.

###Restore your data###
cassandra_snaphotter tries to store data and metadata in a way to make restores less painful; there is not a restore command.

In case you need, cassandra_snapshotter stores the ring token description every time a backup is done ( you can find it the ring file in the snapshot base path )

The way data is stored on S3 should makes it really easy to use the Node Restart Method (http://www.datastax.com/documentation/cassandra/2.0/webhelp/index.html#cassandra/operations/ops_backup_snapshot_restore_t.html#task_ds_cmf_11r_gk)
