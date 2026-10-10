#!/usr/bin/env bash
# Copies what the server needs into the S3 bucket: the processed dataset
# and an archive of the code at the current commit.
#
#   deploy/upload.sh <bucket> [district ...]
#
# With no districts named, every folder under processed/ is copied.
# Uses the AWS profile and region already set in the shell
# (AWS_PROFILE, AWS_REGION). Run it again after new commits or new data:
# only what changed is sent.
set -euo pipefail

BUCKET="${1:?Usage: deploy/upload.sh <bucket> [district ...]}"
shift

cd "$(dirname "$0")/.."

if [ "$#" -gt 0 ]; then
  DISTRICTS=("$@")
else
  DISTRICTS=()
  for folder in processed/*/; do
    DISTRICTS+=("$(basename "$folder")")
  done
fi

for district in "${DISTRICTS[@]}"; do
  echo "Dataset: $district"
  aws s3 sync "processed/$district" "s3://$BUCKET/processed/$district" --only-show-errors
done

ARCHIVE="$(mktemp -d)/shuhul.tar.gz"
git archive --format=tar.gz -o "$ARCHIVE" HEAD
echo "Code: $(git log -1 --format='%h %s')"
aws s3 cp "$ARCHIVE" "s3://$BUCKET/release/shuhul.tar.gz" --only-show-errors
rm -f "$ARCHIVE"

echo "Done. s3://$BUCKET now holds the dataset and release/shuhul.tar.gz"
