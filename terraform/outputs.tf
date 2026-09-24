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

output "urls" {
  description = "Every service, one origin, path-routed by the gateway."
  value = {
    q_engine     = "http://${aws_instance.app.public_dns}/"
    analytics    = "http://${aws_instance.app.public_dns}/analytics/"
    simulator    = "http://${aws_instance.app.public_dns}/simulator/"
    manufacturer = "http://${aws_instance.app.public_dns}/manufacturer/"
    engine_api   = "http://${aws_instance.app.public_dns}/engine/"
    engine_docs  = "http://${aws_instance.app.public_dns}/engine/docs"
  }
}

# Direct container ports stay published for debugging; the paths above are
# the supported entry points.
output "direct_ports" {
  description = "Bypass the gateway (debugging only)."
  value = {
    analytics    = "http://${aws_instance.app.public_dns}:8501/analytics/"
    simulator    = "http://${aws_instance.app.public_dns}:8502/simulator/"
    manufacturer = "http://${aws_instance.app.public_dns}:8503/manufacturer/"
    engine       = "http://${aws_instance.app.public_dns}:8000/"
  }
}

output "ssh_command" {
  description = "SSH into the box to check logs / redeploy."
  value       = "ssh -i ${var.key_pair_name}.pem ec2-user@${aws_instance.app.public_dns}"
}
