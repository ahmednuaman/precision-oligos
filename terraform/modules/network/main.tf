data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  azs = slice(data.aws_availability_zones.available.names, 0, var.az_count)
}

resource "aws_vpc" "this" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = merge(var.tags, { Name = "Vpc-${var.suffix}" })
}

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id
  tags   = merge(var.tags, { Name = "Igw-${var.suffix}" })
}

# Public subnets host only the internet-facing ALB (locked to CloudFront).
resource "aws_subnet" "public" {
  count                   = var.az_count
  vpc_id                  = aws_vpc.this.id
  cidr_block              = cidrsubnet(var.vpc_cidr, 8, count.index)
  availability_zone       = local.azs[count.index]
  map_public_ip_on_launch = false
  tags                    = merge(var.tags, { Name = "PublicSubnet${count.index}-${var.suffix}" })
}

# Private subnets host Fargate tasks and Lambda; AWS access is via VPC endpoints.
resource "aws_subnet" "private" {
  count             = var.az_count
  vpc_id            = aws_vpc.this.id
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, count.index + 100)
  availability_zone = local.azs[count.index]
  tags              = merge(var.tags, { Name = "PrivateSubnet${count.index}-${var.suffix}" })
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.this.id
  }
  tags = merge(var.tags, { Name = "PublicRouteTable-${var.suffix}" })
}

resource "aws_route_table_association" "public" {
  count          = var.az_count
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

# Private route table: no NAT - AWS traffic stays on VPC endpoints.
resource "aws_route_table" "private" {
  vpc_id = aws_vpc.this.id
  tags   = merge(var.tags, { Name = "PrivateRouteTable-${var.suffix}" })
}

resource "aws_route_table_association" "private" {
  count          = var.az_count
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}

# --- Security groups -------------------------------------------------------------------

data "aws_ec2_managed_prefix_list" "cloudfront" {
  name = "com.amazonaws.global.cloudfront.origin-facing"
}

resource "aws_security_group" "alb" {
  name        = "AlbSg-${var.suffix}"
  description = "ALB ingress restricted to the CloudFront origin-facing prefix list."
  vpc_id      = aws_vpc.this.id
  tags        = merge(var.tags, { Name = "AlbSg-${var.suffix}" })

  ingress {
    description     = "HTTP from CloudFront edge only (origin verified by secret header)"
    from_port       = 80
    to_port         = 80
    protocol        = "tcp"
    prefix_list_ids = [data.aws_ec2_managed_prefix_list.cloudfront.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "service" {
  name        = "ApiServiceSg-${var.suffix}"
  description = "Fargate API service; ingress from the ALB only."
  vpc_id      = aws_vpc.this.id
  tags        = merge(var.tags, { Name = "ApiServiceSg-${var.suffix}" })

  ingress {
    description     = "App port from ALB"
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "vpce" {
  name        = "VpcEndpointSg-${var.suffix}"
  description = "Interface VPC endpoints; HTTPS from within the VPC."
  vpc_id      = aws_vpc.this.id
  tags        = merge(var.tags, { Name = "VpcEndpointSg-${var.suffix}" })

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# --- VPC endpoints ---------------------------------------------------------------------

# Gateway endpoints (no ENI cost): S3 (also used for ECR layer pulls) and DynamoDB.
resource "aws_vpc_endpoint" "gateway" {
  for_each          = toset(["s3", "dynamodb"])
  vpc_id            = aws_vpc.this.id
  service_name      = "com.amazonaws.${var.aws_region}.${each.key}"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.private.id]
  tags              = merge(var.tags, { Name = "Vpce-${each.key}-${var.suffix}" })
}

# Interface endpoints so private subnets reach AWS APIs without a NAT gateway.
resource "aws_vpc_endpoint" "interface" {
  for_each = toset([
    "bedrock-runtime",
    "bedrock-agent-runtime",
    "ecr.api",
    "ecr.dkr",
    "logs",
    "sts",
    "sns",
    "sqs",
    "states",
    "secretsmanager",
    "firehose",
  ])
  vpc_id              = aws_vpc.this.id
  service_name        = "com.amazonaws.${var.aws_region}.${each.key}"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.vpce.id]
  private_dns_enabled = true
  tags                = merge(var.tags, { Name = "Vpce-${each.key}-${var.suffix}" })
}
