resource "aws_security_group" "app" {
  name        = "${local.name}-app"
  description = "Single-box NSQ platform - SSH + gateway HTTP only."
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.ssh_cidr]
  }

  ingress {
    description = "HTTP - the gateway, single entry point for every service"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # Everything is served through the gateway on :80 (add :443 when TLS is
  # terminated here). The Streamlit / engine / API container ports are no
  # longer published — they were reachable around the login before.

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.common_tags, { Name = "${local.name}-app-sg" })
}
