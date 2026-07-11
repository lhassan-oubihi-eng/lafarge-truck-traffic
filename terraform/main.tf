terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Backend distant S3 + verrouillage DynamoDB : permet le partage sécurisé
  # du state entre les développeurs et le pipeline Jenkins, avec historique
  # de versions (S3 versioning) et protection contre les exécutions
  # concurrentes (DynamoDB lock).
  backend "s3" {
    bucket         = "lafarge-truck-traffic-tfstate-eu-west3"
    key            = "truck-traffic/terraform.tfstate"
    region         = "eu-west-3"
    dynamodb_table = "lafarge-truck-traffic-tfstate-lock"
    encrypt        = true
  }
}

provider "aws" {
  region = var.aws_region
}

# --------------------------------------------------------------------------
# Données : AMI Amazon Linux 2023 la plus récente (évite les AMI figées)
# --------------------------------------------------------------------------
data "aws_ami" "amazon_linux" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

# --------------------------------------------------------------------------
# VPC
# --------------------------------------------------------------------------
resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = merge(var.tags, {
    Name = "${var.project_name}-vpc"
  })
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = merge(var.tags, {
    Name = "${var.project_name}-igw"
  })
}

# --------------------------------------------------------------------------
# Subnets publics (haute disponibilité sur 2 zones de disponibilité)
# --------------------------------------------------------------------------
resource "aws_subnet" "public" {
  count                   = length(var.public_subnet_cidrs)
  vpc_id                  = aws_vpc.main.id
  cidr_block              = var.public_subnet_cidrs[count.index]
  availability_zone       = var.availability_zones[count.index]
  map_public_ip_on_launch = true

  tags = merge(var.tags, {
    Name = "${var.project_name}-public-subnet-${count.index + 1}"
  })
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = merge(var.tags, {
    Name = "${var.project_name}-public-rt"
  })
}

resource "aws_route_table_association" "public" {
  count          = length(aws_subnet.public)
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

# --------------------------------------------------------------------------
# Security Group : Application Load Balancer
# --------------------------------------------------------------------------
resource "aws_security_group" "alb" {
  name        = "${var.project_name}-alb-sg"
  description = "Allow inbound public HTTP traffic to the Load Balancer"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "Allow HTTP inbound from Internet"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "Unlimited outbound traffic to target EC2 instances"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(var.tags, {
    Name = "${var.project_name}-alb-sg"
  })
}

# --------------------------------------------------------------------------
# Security Group : Instances EC2 applicatives
# --------------------------------------------------------------------------
resource "aws_security_group" "ec2_app" {
  name        = "${var.project_name}-ec2-sg"
  description = "Allow HTTP traffic from ALB and SSH from admin network"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "HTTP only from Load Balancer"
    from_port       = 80
    to_port         = 80
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  ingress {
    description = "Node Exporter metrics accessible within VPC for Prometheus"
    from_port   = 9100
    to_port     = 9100
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  ingress {
    description = "SSH for administration restricted to internal network"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.admin_cidr_ssh]
  }

  egress {
    description = "Unlimited outbound traffic for system updates and Docker image pulls"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(var.tags, {
    Name = "${var.project_name}-ec2-sg"
  })
}

# --------------------------------------------------------------------------
# IAM : rôle d'instance pour AWS Systems Manager (SSM)
# --------------------------------------------------------------------------
resource "aws_iam_role" "ec2_role" {
  name = "${var.project_name}-ec2-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
    }]
  })

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "ssm_managed" {
  role       = aws_iam_role.ec2_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "ec2_profile" {
  name = "${var.project_name}-ec2-instance-profile"
  role = aws_iam_role.ec2_role.name
}

# --------------------------------------------------------------------------
# Application Load Balancer (public)
# --------------------------------------------------------------------------
resource "aws_lb" "app" {
  name               = "${var.project_name}-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = aws_subnet.public[*].id

  enable_deletion_protection = false

  tags = merge(var.tags, {
    Name = "${var.project_name}-alb"
  })
}

resource "aws_lb_target_group" "app" {
  name     = "${var.project_name}-tg"
  port     = 80
  protocol = "HTTP"
  vpc_id   = aws_vpc.main.id

  health_check {
    enabled             = true
    path                = "/healthz"
    protocol            = "HTTP"
    matcher             = "200"
    interval            = 15
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  deregistration_delay = 30

  tags = merge(var.tags, {
    Name = "${var.project_name}-tg"
  })
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.app.arn
  port               = 80
  protocol           = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.app.arn
  }
}

# --------------------------------------------------------------------------
# Launch Template : configuration des instances EC2 applicatives
# --------------------------------------------------------------------------
resource "aws_launch_template" "app" {
  name_prefix   = "${var.project_name}-lt-"
  image_id      = data.aws_ami.amazon_linux.id
  instance_type = var.instance_type

  iam_instance_profile {
    name = aws_iam_instance_profile.ec2_profile.name
  }

  network_interfaces {
    associate_public_ip_address = true
    security_groups             = [aws_security_group.ec2_app.id]
  }

  # Script d'amorçage : installe Docker + Node Exporter, puis démarre le conteneur.
  user_data = base64encode(<<-EOF
    #!/bin/bash
    set -e
    dnf update -y

    # --- Installation et démarrage de Docker ---
    dnf install -y docker
    systemctl enable docker
    systemctl start docker
    usermod -aG docker ec2-user

    # --- Déploiement du conteneur applicatif ---
    docker pull ${var.app_docker_image}
    docker run -d \
      --name truck-traffic-app \
      --restart unless-stopped \
      -p 80:8000 \
      ${var.app_docker_image}

    # --- Installation de Node Exporter ---
    NODE_EXPORTER_VERSION="1.8.2"
    curl -sSL -o /tmp/node_exporter.tar.gz \
      "https://github.com/prometheus/node_exporter/releases/download/v$${NODE_EXPORTER_VERSION}/node_exporter-$${NODE_EXPORTER_VERSION}.linux-amd64.tar.gz"
    tar -xzf /tmp/node_exporter.tar.gz -C /tmp
    mv /tmp/node_exporter-$${NODE_EXPORTER_VERSION}.linux-amd64/node_exporter /usr/local/bin/node_exporter
    useradd --no-create-home --shell /usr/sbin/nologin node_exporter || true

    cat > /etc/systemd/system/node_exporter.service <<'UNIT'
    [Unit]
    Description=Prometheus Node Exporter
    After=network.target

    [Service]
    User=node_exporter
    ExecStart=/usr/local/bin/node_exporter --web.listen-address=:9100

    [Install]
    WantedBy=multi-user.target
    UNIT

    systemctl daemon-reload
    systemctl enable node_exporter
    systemctl start node_exporter
  EOF
  )

  tag_specifications {
    resource_type = "instance"
    tags = merge(var.tags, {
      Name = "${var.project_name}-instance"
    })
  }

  metadata_options {
    http_tokens   = "required" 
    http_endpoint = "enabled"
  }
}

# --------------------------------------------------------------------------
# Auto Scaling Group
# --------------------------------------------------------------------------
resource "aws_autoscaling_group" "app" {
  name                = "${var.project_name}-asg"
  min_size            = var.asg_min_size
  max_size            = var.asg_max_size
  desired_capacity    = var.asg_desired_capacity
  vpc_zone_identifier = aws_subnet.public[*].id
  target_group_arns   = [aws_lb_target_group.app.arn]

  health_check_type         = "ELB"
  health_check_grace_period = 400

  launch_template {
    id      = aws_launch_template.app.id
    version = "$Latest"
  }

  instance_refresh {
    strategy = "Rolling"
    preferences {
      min_healthy_percentage = 50
      instance_warmup        = 60
    }
  }

  tag {
    key                 = "Name"
    value               = "${var.project_name}-asg-instance"
    propagate_at_launch = true
  }

  dynamic "tag" {
    for_each = var.tags
    content {
      key                 = tag.key
      value               = tag.value
      propagate_at_launch = true
    }
  }
}

# --------------------------------------------------------------------------
# Politiques de scaling automatique (Target Tracking CPU)
# --------------------------------------------------------------------------
resource "aws_autoscaling_policy" "scale_out" {
  name                   = "${var.project_name}-scale-out"
  autoscaling_group_name = aws_autoscaling_group.app.name
  policy_type            = "TargetTrackingScaling"

  target_tracking_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ASGAverageCPUUtilization"
    }
    target_value = 60.0
  }
}
