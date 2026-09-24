resource "aws_security_group" "app" {
  name        = "${local.name}-app"
  description = "Single-box NSQ platform - SSH + Streamlit + Q-engine ports."
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.ssh_cidr]
  }

  ingress {
    description = "analytics (Streamlit)"
    from_port   = 8501
    to_port     = 8501
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "simulator (Streamlit)"
    from_port   = 8502
    to_port     = 8502
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTP - the gateway, single entry point for every service"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # Only needed when a system nginx owns :80 and the gateway container is
  # moved to :8080 (GATEWAY_PORT in .env). Harmless otherwise.
  ingress {
    description = "Q-engine gateway (alternate port, when a host nginx owns 80)"
    from_port   = 8080
    to_port     = 8080
    protocol    = "tcp"
    cidr_blocks = var.app_ingress_cidrs
  }

  ingress {
    description = "manufacturer (legacy Streamlit, kept for React-cutover parity)"
    from_port   = 8503
    to_port     = 8503
    protocol    = "tcp"
    cidr_blocks = var.app_ingress_cidrs
  }

  # NOTE: the engine has no authentication of any kind. Exposing it is for
  # debugging convenience; keep var.app_ingress_cidrs narrow (your own IP),
  # or drop this rule once you no longer need to curl it from outside.
  ingress {
    description = "engine (FastAPI scoring API - UNAUTHENTICATED)"
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = var.app_ingress_cidrs
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.common_tags, { Name = "${local.name}-app-sg" })
}
