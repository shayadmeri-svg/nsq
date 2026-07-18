# Minimal footprint: reuse the account's default VPC rather than creating
# a new one (no NAT gateway, no custom subnets/route tables — those cost
# money and add complexity this single-box setup doesn't need).

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

# Pick the first available subnet in the default VPC.
data "aws_subnet" "chosen" {
  id = data.aws_subnets.default.ids[0]
}
