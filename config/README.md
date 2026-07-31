# config/

Holds the Tiger Open API credentials file the client SDK reads at runtime.
Nothing in this directory should ever be committed except this README.

## tiger_openapi_config.properties

Not checked into git (see `.gitignore`). Create it here with the properties
Tiger's Developer Info page gives you for the account you're connecting to
(paper or live):

```
private_key_pk1=<RSA private key, PKCS1>
private_key_pk8=<RSA private key, PKCS8>
tiger_id=<your Tiger ID>
account=<the account number for this properties file>
license=TBSG
env=PROD
```

Use your **paper account**'s file for local development. Only swap in the
live account's file when `TIGER_ENV` is explicitly set to `"live"`.

## If a key ever leaks

If this file, or its private key, is ever committed, pushed, or shared
outside this local environment, regenerate the RSA keypair immediately via
the Tiger Developer Info page — treat the old key as compromised even if
you deleted the file afterward, since a git history rewrite is needed to
actually remove it from a repo's history.
