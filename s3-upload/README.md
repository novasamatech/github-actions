# S3 Upload Action

Upload files or directories to S3-compatible storage (Scaleway, AWS S3, MinIO, etc.).

## Usage

```yaml
- uses: your-org/github-actions-repo/s3-upload@v1
  with:
    s3_region: pl-waw
    s3_access_key: ${{ secrets.SCW_ACCESS_KEY }}
    s3_secret_key: ${{ secrets.SCW_SECRET_KEY }}
    s3_bucket: s3://my-bucket
    source_path: ./app.ipa
    destination_path: /releases/app-1.0.0.ipa
```

## Inputs

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `s3_region` | Yes | - | S3 region |
| `s3_access_key` | Yes | - | Access key |
| `s3_secret_key` | Yes | - | Secret key |
| `s3_bucket` | Yes | - | Bucket URL (e.g., `s3://bucket`) |
| `source_path` | Yes | - | File or directory to upload |
| `destination_path` | Yes | - | Destination path |
| `provider` | No | `scaleway` | Provider (`scaleway`, `aws`, `minio`) |
| `acl` | No | `public-read` | Access control |

## Examples

**Upload file:**
```yaml
source_path: ./app.ipa
destination_path: /releases/app.ipa
```

**Upload directory:**
```yaml
source_path: ./dist/
destination_path: /website/
```

**AWS S3:**
```yaml
provider: aws
s3_region: us-east-1
```
