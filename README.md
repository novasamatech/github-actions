# Reusable GitHub Actions

Collection of reusable GitHub Actions for CI/CD workflows.

## Versioning

Version is managed via [`.version`](.version) file. On every push to `main`, two tags are automatically created/updated:
- Full version tag (e.g., `v1.0.2`) - points to the specific release
- Major version tag (e.g., `v1`) - always points to the latest version within that major version

This allows users to reference either a specific version (`@v1.0.2`) or track the latest major version (`@v1`).

## Actions

### [s3-upload](./s3-upload)

## License

This project is licensed under the [Apache License 2.0](LICENSE).
