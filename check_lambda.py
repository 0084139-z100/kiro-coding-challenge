import boto3
import json

lambda_client = boto3.client('lambda', region_name='us-west-2')
logs_client = boto3.client('logs', region_name='us-west-2')

# Lambda関数の情報を取得
try:
    response = lambda_client.get_function(FunctionName='EventsApiFunction')
    print("Lambda Function Configuration:")
    print(f"Runtime: {response['Configuration']['Runtime']}")
    print(f"Handler: {response['Configuration']['Handler']}")
    print(f"Memory: {response['Configuration']['MemorySize']}")
    print(f"Timeout: {response['Configuration']['Timeout']}")
    print(f"Environment: {response['Configuration'].get('Environment', {})}")
    
    # 最新のログを取得
    print("\n\nFetching recent logs...")
    log_group = '/aws/lambda/EventsApiFunction'
    
    try:
        streams = logs_client.describe_log_streams(
            logGroupName=log_group,
            orderBy='LastEventTime',
            descending=True,
            limit=1
        )
        
        if streams['logStreams']:
            stream_name = streams['logStreams'][0]['logStreamName']
            print(f"Latest log stream: {stream_name}")
            
            events = logs_client.get_log_events(
                logGroupName=log_group,
                logStreamName=stream_name,
                limit=50
            )
            
            print("\nRecent log events:")
            for event in events['events'][-20:]:
                print(event['message'])
        else:
            print("No log streams found")
            
    except Exception as e:
        print(f"Could not fetch logs: {e}")
        
except Exception as e:
    print(f"Error: {e}")
