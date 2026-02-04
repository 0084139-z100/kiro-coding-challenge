import boto3

apigateway_client = boto3.client('apigateway', region_name='us-west-2')

# 既存のAPIを削除
print("Listing existing APIs...")
apis = apigateway_client.get_rest_apis()

for api in apis['items']:
    if api['name'] == 'EventsApi':
        print(f"Deleting API: {api['id']}")
        apigateway_client.delete_rest_api(restApiId=api['id'])
        print("API deleted successfully")

print("\nNow run: python deploy.py")
