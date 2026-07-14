output "distribution_id" { value = aws_cloudfront_distribution.this.id }
output "distribution_domain" { value = aws_cloudfront_distribution.this.domain_name }
output "spa_bucket" { value = aws_s3_bucket.spa.bucket }
output "public_url" {
  value = length(aws_cloudfront_distribution.this.aliases) > 0 ? "https://${tolist(aws_cloudfront_distribution.this.aliases)[0]}" : "https://${aws_cloudfront_distribution.this.domain_name}"
}
