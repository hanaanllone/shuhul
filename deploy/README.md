# Putting Shuhul on AWS

One EC2 machine runs everything with Docker Compose: the database, the API,
the worker and the website. CloudFront sits in front of it for HTTPS and for
caching map tiles. The processed dataset and the code archive live in S3,
and the machine copies both when it first starts.

```
browser ──HTTPS──> CloudFront ──HTTP──> EC2  (web → api, worker, db)
                                         ▲
                              S3: processed/  release/shuhul.tar.gz
```

Cost while it is up: one `t3.medium`, a 30 GB disk, a few GB in S3 and
CloudFront traffic, about 1.30 USD a day in Mumbai. The machine switches
itself off at the time given by the `PowerOffAt` parameter, after which only
the disk is charged. Delete the stack when it is no longer needed.

## Before you start

- AWS CLI v2, signed in as a user who can use S3, EC2, CloudFront and
  CloudFormation, and can create the `shuhul-ec2` role
  (`deploy/iam-shuhul-roles.json` is a policy that allows just that).
- The processed dataset in `processed/`.
- Everything you want deployed is committed: the archive is made from the
  current commit.

```bash
export AWS_PROFILE=shuhul
export AWS_REGION=ap-south-1
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
BUCKET=shuhul-data-$ACCOUNT
```

## 1. Create the bucket and upload

```bash
aws s3api create-bucket --bucket $BUCKET \
  --create-bucket-configuration LocationConstraint=$AWS_REGION
aws s3api put-public-access-block --bucket $BUCKET \
  --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true

bash deploy/upload.sh $BUCKET
```

To upload only some districts, name them: `bash deploy/upload.sh $BUCKET sxr sr-c`.

## 2. Create the stack

```bash
PREFIX_LIST=$(aws ec2 describe-managed-prefix-lists \
  --filters Name=prefix-list-name,Values=com.amazonaws.global.cloudfront.origin-facing \
  --query "PrefixLists[0].PrefixListId" --output text)

aws cloudformation deploy \
  --stack-name shuhul \
  --template-file deploy/stack.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides DataBucket=$BUCKET CloudFrontPrefixList=$PREFIX_LIST

aws cloudformation describe-stacks --stack-name shuhul \
  --query "Stacks[0].Outputs" --output table
```

The stack takes about ten minutes, most of it CloudFront. The machine then
needs roughly another ten to install Docker, copy the dataset and build the
images. `SiteUrl` in the outputs is the address.

To watch the first start:

```bash
aws ec2 get-console-output --instance-id <InstanceId> --latest --output text | tail -40
```

It ends with `Shuhul setup finished`.

## 3. Releasing a change

```bash
bash deploy/upload.sh $BUCKET
```

That is all. Every three minutes the machine checks the archive in the
bucket; when it has changed it fetches the code and any new data and
rebuilds. To see how that went, and what the app is doing:

```bash
aws s3 cp s3://$BUCKET/logs/status.txt -
```

The same file is refreshed every fifteen minutes.

## Turning on report analysis

Reading news reports with a language model uses Amazon Bedrock. Once the
account has model access, pass the model or inference profile id:

```bash
aws cloudformation deploy --stack-name shuhul --template-file deploy/stack.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides DataBucket=$BUCKET CloudFrontPrefixList=$PREFIX_LIST BedrockModelId=<id>
```

Changing this parameter replaces the machine, so projects and accounts made
on the old one are lost. To keep them, open a shell on the machine with
`aws ssm start-session --target <InstanceId>`, set `SHUHUL_BEDROCK_MODEL_ID`
in `/srv/shuhul/.env` and run `docker compose up -d` in `/srv/shuhul`.

## Taking it down

```bash
aws cloudformation delete-stack --stack-name shuhul
aws s3 rb s3://$BUCKET --force
```

## What to know

- The link between CloudFront and the machine is plain HTTP. Visitors always
  get HTTPS, but for anything beyond a demonstration the machine should have
  its own certificate and domain.
- The database is a container on the same disk. Deleting the stack deletes
  the accounts and projects in it.
- The machine's address changes if it is stopped and started, which
  includes the automatic switch-off, and CloudFront would then point at the
  old one. To bring it back, start the machine and update the stack.
- The machine runs on standard CPU credits, so a long busy spell slows it
  down instead of adding to the bill.
- `docker-compose.yml` runs the app in production mode, where sign-in needs
  HTTPS. For work on your own computer use the development servers described
  in the main README.
