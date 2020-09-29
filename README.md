# aws-eb-update-notifier

Drops a notification in Slack if updates are available for AWS Elastic Beanstalk environments

## Purpose

AWS frequently releases updates for Elastic Beanstalk and does have a managed updates feature whereby updates are automatically applied.  However, if you want to control the updates on your schedule (say for environments that deal with long running jobs), there's no way to get a notification if an update is available, beyond randomly finding it in the console.

This solution is a scheduled lambda function which runs weekly and checks each EB environment in the current region to see if it has an update pending.  If it does, a notification is sent to Slack with the details.

## Prerequsites

- python3 and pip3 must be installed
- You'll need to setup a [Slack bot](https://slack.com/intl/en-ca/help/articles/115005265703-Create-a-bot-for-your-workspace) and obtain the oAuth token for your bot.  The oAuth token is under Features->oAuth and Permissions.
- This oAuth token will need to be stored in [AWS parameter store](https://docs.aws.amazon.com/systems-manager/latest/userguide/systems-manager-parameter-store.html) as a secure string
- The Slack bot will need to be a member of the channel you wish to post to (`/invite @mybot`)
- You'll need the ID of the KMS key used to encrypt your SSM secure string parameter

## Installing

Everything is packaged with [aws sam](https://aws.amazon.com/serverless/sam/).  You'll want to install one application in each region you have ES clusters.  Clone this repo and run:

```bash
sam build

sam deploy \
    --stack-name eb-update-notifier \
    --s3-bucket <an existing bucket to store lambda sam apps in> \
    --profile staging \
    --region us-east-1 \
    --capabilities CAPABILITY_IAM \
     --parameter-overrides "SlackChannel=#alerts \
                            KMSDecryptSSMKeyID=abcdget-1234-e456-123455 \
                            SlackBotOAuthTokenSSMPath=/devops/slack/MYBOT_OAUTH_TOKEN"
```

Repeat the `sam deploy` for each region, ensuring that the KMS key ID and the SSM path are correct for each region.
