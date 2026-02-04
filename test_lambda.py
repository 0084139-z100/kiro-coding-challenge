import boto3
import json

lambda_client = boto3.client('lambda', region_name='us-west-2')

# テストイベント
test_event = {
    "httpMethod": "GET",
    "path": "/",
    "headers": {},
    "queryStringParameters": None,
    "body": None,
    "isBase64Encoded": False
}

print("Testing Lambda function...")
print(f"Event: {json.dumps(test_event, indent=2)}")

try:
    response = lambda_client.invoke(
        FunctionName='EventsApiFunction',
        InvocationType='RequestResponse',
        Payload=json.dumps(test_event)
    )
    
    payload = json.loads(response['Payload'].read())
    print(f"\nResponse:")
    print(json.dumps(payload, indent=2))
    
    if 'FunctionError' in response:
        print(f"\nFunction Error: {response['FunctionError']}")
        
except Exception as e:
    print(f"Error invoking function: {e}")
