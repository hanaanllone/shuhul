# Putting Shuhul on AWS

One EC2 machine runs everything with Docker Compose: the database, the API,
the worker and the website, which serves HTTPS itself. The processed dataset
and the code archive live in S3. The machine copies both when it first
starts, and again whenever a new archive is uploaded.

```
browser ──HTTPS──> EC2  (web → api, worker, db)
                    ▲
         S3: processed/  release/shuhul.tar.gz  logs/status.txt
```

Cost while it is up: one `c7i-flex.large`, a 30 GB disk, one public address
and a few GB in S3, about 2.25 USD a day in Mumbai. The machine switches
itself off at the time given by the `PowerOffAt` parameter, after which only
the disk and the address are charged. Delete the stack when it is no longer
needed.

An account on the AWS Free plan can only start instance types marked
free-tier eligible. List them with:

```bash
aws ec2 describe-instance-types --filters Name=free-tier-eligible,Values=true \
  --query "InstanceTypes[].InstanceType" --output text
```

## Before you start

- AWS CLI v2, signed in as a user who can use S3, EC2 and CloudFormation,
  and can create the `shuhul-ec2` role
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
aws cloudformation deploy \
  --stack-name shuhul \
  --template-file deploy/stack.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides DataBucket=$BUCKET

aws cloudformation describe-stacks --stack-name shuhul \
  --query "Stacks[0].Outputs" --output table
```

The stack takes a few minutes. The machine then needs roughly another ten to
install Docker, copy the dataset and build the images. `SiteUrl` in the
outputs is the address.

### The address

With nothing else said, the site is served at a name made from the machine's
address, such as `https://13-234-56-78.sslip.io`. sslip.io is a public
service that resolves such names to the address inside them, which lets the
web server get an HTTPS certificate without a domain of your own.

If you have a domain, point it at the machine and pass it:
`--parameter-overrides DataBucket=$BUCKET SiteHost=maps.example.org`.

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
account has model access, open a shell on the machine with
`aws ssm start-session --target <InstanceId>`, set `SHUHUL_BEDROCK_MODEL_ID`
in `/srv/shuhul/.env` and run `docker compose up -d` in `/srv/shuhul`.

Passing `BedrockModelId` to the stack does the same for a new machine, but
on an existing stack it replaces the machine, and the accounts and projects
on it are lost.

## Taking it down

```bash
aws cloudformation delete-stack --stack-name shuhul
aws s3 rb s3://$BUCKET --force
```

## What to know

- The database is a container on the same disk. Deleting the stack deletes
  the accounts and projects in it.
- The site keeps its address when the machine is stopped and started, which
  includes the automatic switch-off. Start it again from the EC2 console or
  with `aws ec2 start-instances --instance-ids <InstanceId>`.
- With a burstable instance type such as `t3.small`, pass
  `CpuCredits=standard` so a long busy spell slows the machine down instead
  of adding to the bill.
- A new AWS account that has not been verified yet cannot create CloudFront
  distributions or call Bedrock, which is why this setup needs neither to
  serve the site.
- `docker-compose.yml` runs the app in production mode, where sign-in needs
  HTTPS. For work on your own computer use the development servers described
  in the main README.
