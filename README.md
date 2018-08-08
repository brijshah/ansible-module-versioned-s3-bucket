# Ansible Module

Custom ansible moduls not yet submitted or accepted by [Ansible](https://github.com/ansible/ansible).

## Usage

#### s3_versioned_bucket

An Ansible module to do delete versioned AWS S3 buckets.

**Task Examples**

```yml
# delete mys3bucket, force will ensure all versioned objects are removed prior to deletion
- s3_versioned_bucket:
    name: mys3bucket
    state: absent
    force: yes
```

**Options**

| Parameter | Required | Default | Choices | Comments |
|-----------|----------|---------|---------|----------|
| aws_access_key | no  |         |         | AWS access key. If not set then the value of the AWS_ACCESS_KEY_ID, AWS_ACCESS_KEY or EC2_ACCESS_KEY environment variable is used. |
| aws_secret_key | no  |         |         | AWS secret key. If not set then the value of the AWS_SECRET_ACCESS_KEY, AWS_SECRET_KEY, or EC2_SECRET_KEY environment variable is used. |
| profile   | no       |         |         | Uses a boto profile. Only works with boto >= 2.24.0. |
| region    | no       |         |         | The AWS region to use. If not specified then the value of the AWS_REGION or EC2_REGION environment variable, if any, is used. See http://docs.aws.amazon.com/general/latest/gr/rande.html#ec2_region |
| security_token | no  |         |         | AWS STS security token. If not set then the value of the AWS_SECURITY_TOKEN or EC2_SECURITY_TOKEN environment variable is used. |
| force     | bool |         |         | When trying to delete a bucket, delete all keys in the bucket first (an s3 bucket must be empty for a successful deletion) |
| name  | yes |     |         | Name of the s3 bucket |
| state | yes | absent | `present` or `absent` | Create or remove the s3 bucket |


## Integration

> Assuming you are in the root folder of your ansible project.

Specify a module path in your ansible configuration file.

```shell
$ vim ansible.cfg
```
```ini
[defaults]
...
library = ./library
...
```

Create the directory and copy the python modules into that directory

```shell
$ mkdir library
$ cp path/to/module library
```
