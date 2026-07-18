output "instance_id" {
  description = "EC2 instance ID."
  value       = aws_instance.app.id
}

output "public_ip" {
  description = "Public IPv4 address of the instance."
  value       = aws_instance.app.public_ip
}

output "public_dns" {
  description = "Public DNS name (ec2-x-x-x-x.compute-1.amazonaws.com style)."
  value       = aws_instance.app.public_dns
}

output "analytics_url" {
  description = "Analytics dashboard."
  value       = "http://${aws_instance.app.public_dns}/analytics"
}

output "simulator_url" {
  description = "Simulator workbench."
  value       = "http://${aws_instance.app.public_dns}/simulator"
}

output "ssh_command" {
  description = "SSH into the box to check logs / redeploy."
  value       = "ssh -i ${var.key_pair_name}.pem ec2-user@${aws_instance.app.public_dns}"
}
