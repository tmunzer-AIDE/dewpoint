// SPDX-License-Identifier: Apache-2.0

// Package auditbucket writes the authorizer's audit records to D6's bucket (internal/audit has the record).
package auditbucket

import (
	"bytes"
	"context"
	"encoding/json"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/s3"

	"dewpoint.local/temporal-server/internal/audit"
)

// PutAPI is the one S3 call the writer makes.
type PutAPI interface {
	PutObject(ctx context.Context, in *s3.PutObjectInput, opts ...func(*s3.Options)) (*s3.PutObjectOutput, error)
}

// Writer writes each record as one object, conditionally (`If-None-Match: *`), so a record is never overwritten. It sets
// no retention: the bucket's compliance-mode default applies (D6.9 checks it). Its credentials are the authorizer's
// own, allowed to put under `temporal-authorizer/` and nothing else.
type Writer struct {
	Client PutAPI
	Bucket string
	Prefix string
}

func (w Writer) Write(ctx context.Context, r audit.Record) error {
	body, err := json.Marshal(r)
	if err != nil {
		return err
	}
	_, err = w.Client.PutObject(ctx, &s3.PutObjectInput{
		Bucket:      aws.String(w.Bucket),
		Key:         aws.String(audit.Key(w.Prefix, r)),
		Body:        bytes.NewReader(body),
		ContentType: aws.String("application/json"),
		IfNoneMatch: aws.String("*"),
	})
	return err
}

// NewClient is an S3 client from the standard AWS settings (credentials from the environment or its files, never
// from this server's configuration); `endpoint` set for a non-AWS server such as the proof's MinIO, path-style.
func NewClient(ctx context.Context, region, endpoint string) (*s3.Client, error) {
	cfg, err := config.LoadDefaultConfig(ctx, config.WithRegion(region))
	if err != nil {
		return nil, err
	}
	return s3.NewFromConfig(cfg, func(o *s3.Options) {
		if endpoint != "" {
			o.BaseEndpoint = aws.String(endpoint)
			o.UsePathStyle = true
		}
	}), nil
}
