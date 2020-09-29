import json
import boto3
from botocore.exceptions import ClientError
import os
from packaging import version
from slack import WebClient
from slack.errors import SlackApiError

boto_session = boto3.session.Session()
eb_client = boto_session.client('elasticbeanstalk')
ssm_client = boto_session.client('ssm')
iam_client = boto_session.client('iam')

# Global cache to keep from listing the platform versions each time
latest_platform_version_cache = {}

def get_aws_account_alias(iam_client):
    account_alias = None
    
    try:
        account_alias = iam_client.list_account_aliases()['AccountAliases'][0]
    except ClientError as ex:
        print("Unable to get current aws account ID: {}".format(ex.response['Error']['Code']))

    return account_alias

def get_slack_token(ssm_client, token_path):
    param_val = None

    try:
        response = ssm_client.get_parameter(Name=token_path, WithDecryption=True)
        param_val = response['Parameter']['Value']
    except ClientError as ex:
        print("Unable to retrieve parameter from parameter store: {}".format(ex.response['Error']['Code']))

    return param_val

def get_latest_platform_version(platform_name):
    global latest_platform_version_cache
    global eb_client

    latest_version = None

    if platform_name in latest_platform_version_cache:
        latest_version = latest_platform_version_cache[platform_name]
    else:
        filters = [
            {
                'Type': 'PlatformName',
                'Operator': '=',
                'Values': [platform_name],
            },
            {
                'Type': 'PlatformVersion',
                'Operator': '=',
                'Values': ["latest"],
            }
        ]

        # When filtering for latest, we will only get back one entry
        try:
            latest_platform_version = eb_client.list_platform_versions(Filters=filters)

            latest_version = latest_platform_version['PlatformSummaryList'][0]['PlatformVersion']
            latest_platform_version_cache[platform_name] = latest_version
        except ClientError as ex:
            print("Unable to retrieve latest platform list: {}".format(ex.response['Error']['Code']))

    return latest_version

def get_platform_version(platform_arn):
    # arn:aws:elasticbeanstalk:us-east-1::platform/Puma with Ruby 2.6 running on 64bit Amazon Linux/2.11.10
    return platform_arn.split(':')[5].split('/')[2]

def get_platform_name(platform_arn):
    # arn:aws:elasticbeanstalk:us-east-1::platform/Puma with Ruby 2.6 running on 64bit Amazon Linux/2.11.10
    return platform_arn.split(':')[5].split('/')[1]

def lambda_handler(event, context):
    applications = None

    try:
        applications = eb_client.describe_applications()
    except ClientError as ex:
        print("Unable to obtain list of EB applications: {}".format(ex.response['Error']['Code']))

    if applications:
        for application in applications['Applications']:
            environments = None
            eb_application_name = application['ApplicationName']

            print("EB application found: " + eb_application_name)

            try:
                environments = eb_client.describe_environments(
                    ApplicationName = application['ApplicationName'],
                    IncludeDeleted = False
                )
            except ClientError as ex:
                print("Unable to obtain list of EB environments: {}".format(ex.response['Error']['Code']))

            if environments:
                for environment in environments['Environments']:
                    environment_name = environment['EnvironmentName']
                    environment_id = environment['EnvironmentId']
                    print("EB environment found: " + environment_name + "(" + environment_id + ")")

                    platform_name = get_platform_name(environment['PlatformArn'])
                    current_platform_version = get_platform_version(environment['PlatformArn'])

                    print("Current platform: " + platform_name + " Platform version: " + current_platform_version)

                    latest_platform_version = get_latest_platform_version(platform_name)
                    print("Latest available version for " +  platform_name + " is " + str(latest_platform_version))

                    if version.parse(latest_platform_version) > version.parse(current_platform_version):
                        print("A newer version (" + str(latest_platform_version) + ") is available for " + environment_name)

                        eb_release_notes_url = 'https://docs.aws.amazon.com/elasticbeanstalk/latest/relnotes/relnotes.html'
                        eb_console_url = 'https://console.aws.amazon.com/elasticbeanstalk/home?region=' + boto_session.region_name + '#/environment/dashboard?applicationName=' + eb_application_name + '&environmentId=' + environment_id

                        slack_token = get_slack_token(ssm_client,os.environ['SLACK_TOKEN_SSM_PATH'])
                        slack_channel = os.environ['SLACK_CHANNEL']

                        if slack_token:
                            print("Posting notification to Slack")
                            slack_client = WebClient(token=slack_token)

                            try:
                                response = slack_client.chat_postMessage(
                                    channel=slack_channel,
                                    blocks=[
                                                {
                                                    "type": "section",
                                                    "text": {
                                                        "type": "mrkdwn",
                                                        "text": "A new Elastic Beanstalk container version is available for\n*<" + eb_console_url + "|" + eb_application_name + '/' + environment_name + ">*"
                                                    }
                                                },
                                                 {
                                                    "type": "section",
                                                    "fields": [
                                                        {
                                                            "type": "mrkdwn",
                                                            "text": "*AWS Account:*\n" + get_aws_account_alias(iam_client)
                                                        },
                                                        {
                                                            "type": "mrkdwn",
                                                            "text": "*Region:*\n" + boto_session.region_name
                                                        }
                                                    ]
                                                },
                                                {
                                                    "type": "section",
                                                    "fields": [
                                                        {
                                                            "type": "mrkdwn",
                                                            "text": "*Platform:*\n" + platform_name + "\n"
                                                        },
                                                        {
                                                            "type": "mrkdwn",
                                                            "text": " "
                                                        },
                                                        {
                                                            "type": "mrkdwn",
                                                            "text": "*Current Version:*\n" + str(current_platform_version)
                                                        },
                                                        {
                                                            "type": "mrkdwn",
                                                            "text": "New Version:\n*<" + eb_release_notes_url + "|" + str(latest_platform_version) + ">*"
                                                        }
                                                    ]
                                                },
                                                 {
                                                    "type": "divider"
                                                }
                                            ]
                                )
                            except SlackApiError as e:
                                # You will get a SlackApiError if "ok" is False
                                assert e.response["ok"] is False
                                assert e.response["error"]  # str like 'invalid_auth', 'channel_not_found'
                                print(f"Error posting to Slack: {e.response['error']}")
                    else:
                        print("Environment " + environment_name + " is running the latest version (" + str(latest_platform_version) +  ")")

if __name__ == '__main__':
    lambda_handler(None, None)
