#!/usr/bin/python

ANSIBLE_METADATA = {'metadata_version': '1.0',
                    'status': ['preview'],
                    'supported_by': 'community'}


DOCUMENTATION = '''
---
module: s3_versioned_bucket
short_description: Manage Versioned S3 buckets in AWS
description:
    - Manage S3 buckets in AWS
version_added: "2.5"
requirements: [ boto3 ]
author: "Brij Shah"
options:
  force:
    description:
      - When trying to delete a bucket, delete all keys in the bucket first (an s3 bucket must be empty for a successful deletion)
    type: bool
    default: 'no'
  name:
    description:
      - Name of the s3 bucket
    required: true
  state:
    description:
      - Create or remove the s3 bucket
    required: false
    default: present
    choices: [ 'present', 'absent' ]
extends_documentation_fragment:
    - aws
    - ec2
'''

EXAMPLES = '''
# Note: These examples do not set authentication details, see the AWS Guide for details.

# Remove an s3 bucket and any keys it contains
- s3_versioned_bucket:
    name: mys3bucket
    state: absent
    force: yes
'''

import json
import os
import time

from ansible.module_utils.basic import to_text
from ansible.module_utils.aws.core import AnsibleAWSModule
from ansible.module_utils.ec2 import ec2_argument_spec
from ansible.module_utils.ec2 import get_aws_connection_info, boto3_conn, AWSRetry

try:
    from botocore.exceptions import BotoCoreError, ClientError, EndpointConnectionError, WaiterError
except ImportError:
    pass  # handled by AnsibleAWSModule


def bucket_exists(s3_client, bucket_name):
    all_buckets = s3_client.list_buckets(Bucket=bucket_name)['Buckets']
    return any(bucket['Name'] == bucket_name for bucket in all_buckets)


@AWSRetry.exponential_backoff(max_delay=120, catch_extra_error_codes=['NoSuchBucket'])
def get_bucket_versioning(s3_client, bucket_name):
    return s3_client.get_bucket_versioning(Bucket=bucket_name)

@AWSRetry.exponential_backoff(max_delay=120, catch_extra_error_codes=['NoSuchBucket'])
def put_bucket_versioning(s3_client, bucket_name, required_versioning):
    s3_client.put_bucket_versioning(Bucket=bucket_name, VersioningConfiguration={'Status': required_versioning})

def wait_versioning_is_applied(module, s3_client, bucket_name, required_versioning):
    for dummy in range(0, 12):
        try:
            versioning_status = get_bucket_versioning(s3_client, bucket_name)
        except (BotoCoreError, ClientError) as e:
            module.fail_json_aws(e, msg="Failed to get updated versioning for bucket")
        if versioning_status.get('Status') != required_versioning:
            time.sleep(5)
        else:
            return versioning_status
    module.fail_json(msg="Bucket versioning failed to apply in the excepted time")

@AWSRetry.exponential_backoff(max_delay=120)
def delete_bucket(s3_client, bucket_name):
    try:
        s3_client.delete_bucket(Bucket=bucket_name)
    except ClientError as e:
        if e.response['Error']['Code'] == 'NoSuchBucket':
            # This means bucket should have been in a deleting state when we checked it existence
            # We just ignore the error
            pass
        else:
            raise e


def destroy_bucket(s3_client, module, name):

    force = module.params.get("force")
    name = module.params.get("name")
    try:
        bucket_is_present = bucket_exists(s3_client, name)
    except EndpointConnectionError as e:
        module.fail_json_aws(e, msg="Invalid endpoint provided: %s" % to_text(e))
    except (BotoCoreError, ClientError) as e:
        module.fail_json_aws(e, msg="Failed to check bucket presence")

    if not bucket_is_present:
        module.exit_json(changed=False)

    if force:
        # if there are versioned contents then we need to delete them before we can delete the bucket
        try:
            versioning_status = get_bucket_versioning(s3_client, name)
        except (ClientError, BotoCoreError) as e:
            module.fail_json_aws(e, msg="Failed to get bucket versioning")
        
        if versioning_status.get('Status') == "Enabled":
            required_versioning = 'Suspended'

        if required_versioning:
            try:
                put_bucket_versioning(s3_client, name, required_versioning)
                changed = True
            except (BotoCoreError, ClientError) as e:
                module.fail_json_aws(e, msg="Failed to update bucket versioning")
        
        versioning_status = wait_versioning_is_applied(module, s3_client, name, required_versioning)

        paginator = s3_client.get_paginator('list_object_versions')
        page_iterator = paginator.paginate(Bucket=name)

        for page in page_iterator:
            if 'DeleteMarkers' in page:
                delete_markers = page['DeleteMarkers']
                if delete_markers is not None:
                    for delete_marker in delete_markers:
                        key = delete_marker['Key']
                        versionId = delete_marker['VersionId']
                        s3_client.delete_object(Bucket=name, Key=key, VersionId=versionId)
            if 'Versions' in page and page['Versions'] is not None:
                versions = page['Versions']
                for version in versions:
                    key = version['Key']
                    versionId = version['VersionId']
                    s3_client.delete_object(Bucket=name, Key=key, VersionId=versionId)

        object_paginator = s3_client.get_paginator('list_objects_v2')
        page_iterator = object_paginator.paginate(Bucket=name)
        
        for page in page_iterator:
            if 'Contents' in page:
                for content in page['Contents']:
                    key = content['Key']
                    s3_client.delete_object(Bucket=bucket_name, Key=content['Key'])

    try:
        delete_bucket(s3_client, name)
        s3_client.get_waiter('bucket_not_exists').wait(Bucket=name)
    except WaiterError as e:
        module.fail_json_aws(e, msg='An error occurred waiting for the bucket to be deleted.')
    except (BotoCoreError, ClientError) as e:
        module.fail_json_aws(e, msg="Failed to delete bucket")

    module.exit_json(changed=True)


def get_s3_client(module, aws_connect_kwargs, location):
    params = dict(module=module, conn_type='client', resource='s3', region=location, **aws_connect_kwargs)
    return boto3_conn(**params)


def main():

    argument_spec = ec2_argument_spec()
    argument_spec.update(
        dict(
            force=dict(required=False, default='no', type='bool'),
            name=dict(required=True, type='str'),
            state=dict(default='present', type='str', choices=['present', 'absent'])
        )
    )

    module = AnsibleAWSModule(argument_spec=argument_spec)

    region, ec2_url, aws_connect_kwargs = get_aws_connection_info(module, boto3=True)

    if region in ('us-east-1', '', None):
        # default to US Standard region
        location = 'us-east-1'
    else:
        # Boto uses symbolic names for locations but region strings will
        # actually work fine for everything except us-east-1 (US Standard)
        location = region

    s3_client = get_s3_client(module, aws_connect_kwargs, location)

    if s3_client is None:  # this should never happen
        module.fail_json(msg='Unknown error, failed to create s3 connection, no information from boto.')

    state = module.params.get("state")
    name = module.params.get("name")

    # if state == 'present':
    #     create_or_update_bucket(s3_client, module, location)
    if state == 'absent':
        destroy_bucket(s3_client, module, name)


if __name__ == '__main__':
    main()