openapi-generator-cli generate \
    -i Finalizer/ApiPushToDb/swagger.json \
    -g python \
    -o Finalizer/ApiPushToDb/backend-api-client \
    --additional-properties=packageName=backend_api_client \
    --additional-properties=packageVersion=1.0.0 \
    --additional-properties=projectName=backend_api_client