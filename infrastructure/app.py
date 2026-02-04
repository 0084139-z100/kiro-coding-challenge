#!/usr/bin/env python3
import aws_cdk as cdk
from infrastructure.infrastructure_stack import InfrastructureStack

app = cdk.App()
InfrastructureStack(app, "InfrastructureStack",
    env=cdk.Environment(region="us-west-2")
)

app.synth()
