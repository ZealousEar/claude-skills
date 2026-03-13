# Grapple Law — Database Schema Reference

Injected into every Ralph analytics prompt. PostgreSQL (Supabase-hosted), locally loaded for analysis.

## Tables & Columns

### users (~1748 rows)
| Column | Type | Notes |
|--------|------|-------|
| id | uuid PK | |
| email | text | PII — aggregate only |
| first_name | text | PII |
| last_name | text | PII |
| address_line1, address_line2, city, country, postcode | text | PII |
| is_id_deferred | boolean | ID verification deferred |
| is_marketing_accepted | boolean | Marketing consent |
| is_terms_accepted | boolean | Terms acceptance |
| pending_plan_id | uuid | FK to subscriptions — user saw pricing but didn't complete |
| stripe_customer_id | text | Stripe link |
| roles | **NOT a column** | Roles stored in `users_roles` join table, NOT on users table directly |
| verified | boolean | Email verified |
| login_attempts | integer | |
| created_at | timestamptz | Registration timestamp |
| updated_at | timestamptz | |

### sessions (~10672 rows)
| Column | Type | Notes |
|--------|------|-------|
| id | uuid PK | |
| ref_number | text | Human-readable reference |
| case_details | text | May be structured or free text |
| user_id | uuid FK → users | |
| messages_sent_today_count | integer | Daily message counter |
| is_max_free_messages_count_reached | boolean | Paywall trigger flag |
| thread_locked_at | timestamptz | When thread was locked |
| created_at | timestamptz | |
| updated_at | timestamptz | |

### session_messages (~293424 rows)
| Column | Type | Notes |
|--------|------|-------|
| id | uuid PK | |
| session_id | uuid FK → sessions | |
| message | **jsonb** | **CRITICAL: JSONB not text!** LangChain format. Keys: `content` (text), `type` (ai/human/system), `metadata`, `response_metadata`, `additional_kwargs`, `tool_calls`, `invalid_tool_calls`, `llm_run_metadata`. Use `message->>'content'` for text, `message->>'type'` for sender type. |
| system_type | enum_session_messages_system_type | Values: 'email-inbound' (568), 'ms-user-import-data' (84), 'user-info' (2298), NULL=regular chat (290472) |
| email_id | uuid FK → emails | Nullable — links to email when message is email-related |
| created_at | timestamptz | |
| updated_at | timestamptz | |

### emails (~2437 rows)
| Column | Type | Notes |
|--------|------|-------|
| id | uuid PK | |
| user_id | uuid FK → users | |
| session_id | uuid FK → sessions | |
| date | timestamptz | Email date |
| is_inbound | boolean | true = received, false = sent by Grapple |
| from_email | text | |
| from_name | text | |
| subject | text | |
| content | text | Full email body |
| content_type | text | MIME type |
| metadata | json | Additional email metadata |
| created_at | timestamptz | |
| updated_at | timestamptz | |

### subscriptions (plan definitions)
| Column | Type | Notes |
|--------|------|-------|
| id | uuid PK | |
| name | text | Plan name |
| amount | decimal | Price |
| payment_period | text | e.g. 'monthly' |
| description | text | |
| rich_description | text | |
| rich_description_html | text | |
| description_mode | enum_subscriptions_description_mode | 'richtext', 'html', 'plaintext' |
| is_hidden | boolean | |
| is_default | boolean | |
| is_popular | boolean | |
| is_auto_renew | boolean | |
| is_no_win_no_fee | boolean | DBA/contingent fee plan |
| use_stripe | boolean | |
| stripe_product_id | text | |
| stripe_price_id | text | |
| stripe_price_lookup_key | enum | Stripe lookup key |
| sort_order | integer | |
| created_at | timestamptz | |
| updated_at | timestamptz | |

### users_subscriptions (~1120 rows)
| Column | Type | Notes |
|--------|------|-------|
| id | uuid PK | |
| subscription_id | uuid FK → subscriptions | |
| user_id | uuid FK → users | |
| status | enum_users_subscriptions_status | 'active', 'inactive', 'deleted', 'unpaid' |
| last_processed_stripe_event_id | text | |
| created_at | timestamptz | |
| updated_at | timestamptz | |

### subscription_capabilities
| Column | Type | Notes |
|--------|------|-------|
| id | uuid PK | |
| capability | enum | 'CHAT', 'EMAILS', 'FILE_UPLOADS' |
| description | text | |
| created_at | timestamptz | |

### subscriptions_capabilities (join table)
| Column | Type | Notes |
|--------|------|-------|
| id | uuid PK | |
| parent_id | uuid FK → subscriptions | |
| subscription_capabilities_id | uuid FK → subscription_capabilities | |
| sort_order | integer | |

### subscriptions_features
| Column | Type | Notes |
|--------|------|-------|
| id | uuid PK | |
| parent_id | uuid FK → subscriptions | |
| feature | text | |
| sort_order | integer | |

### emails_to_emails
| Column | Type | Notes |
|--------|------|-------|
| id | uuid PK | |
| parent_id | uuid FK → emails | |
| email | text | Recipient email |
| name | text | Recipient name |
| sort_order | integer | |

### emails_attachments
| Column | Type | Notes |
|--------|------|-------|
| id | uuid PK | |
| parent_id | uuid FK → emails | |
| users_media_id | uuid FK → users_media | |
| sort_order | integer | |

### session_messages_attachments
| Column | Type | Notes |
|--------|------|-------|
| id | uuid PK | |
| parent_id | uuid FK → session_messages | |
| users_media_id | uuid FK → users_media | |
| sort_order | integer | |

### users_roles (~1746 rows)
| Column | Type | Notes |
|--------|------|-------|
| id | uuid PK | |
| order | integer | |
| parent_id | uuid FK → users | |
| value | enum_users_roles | 'admin', 'client', 'api' |

### users_sessions (~1997 rows)
| Column | Type | Notes |
|--------|------|-------|
| id | varchar PK | Session token |
| _order | integer | |
| _parent_id | uuid FK → users | |
| created_at | timestamptz | |
| expires_at | timestamptz | |

### users_media
| Column | Type | Notes |
|--------|------|-------|
| id | uuid PK | |
| user_id | uuid FK → users | |
| filename | text | |
| original_file_name | text | |
| mime_type | text | |
| filesize | integer | |
| width | integer | |
| height | integer | |
| url | text | |
| created_at | timestamptz | |
| updated_at | timestamptz | |

## Key Relationships
```
users 1→N sessions (user_id)
users 1→N users_subscriptions (user_id)
users 1→N emails (user_id)
users 1→N users_media (user_id)
sessions 1→N session_messages (session_id)
sessions 1→N emails (session_id)
session_messages N→1 emails (email_id, nullable)
subscriptions 1→N users_subscriptions (subscription_id)
subscriptions 1→N subscriptions_capabilities (parent_id)
subscriptions 1→N subscriptions_features (parent_id)
emails 1→N emails_to_emails (parent_id)
emails 1→N emails_attachments (parent_id)
session_messages 1→N session_messages_attachments (parent_id)
```

## Critical SQL Notes

1. **JSONB messages:** `session_messages.message` is JSONB in LangChain format. Use `message->>'content'` for text content, `message->>'type'` for sender ('ai', 'human', 'system'). Do NOT use `message.key` syntax.
2. **ENUM types:** system_type, roles, status are ENUMs — cast with `::text` when comparing in LIKE expressions. Users roles include 'admin', 'client', 'api'. Subscription status includes 'active', 'inactive', 'deleted', 'unpaid', 'past_due'.
3. **Aggregation preferred:** With ~293K rows in session_messages, always use GROUP BY, COUNT, AVG. Avoid SELECT * on this table.
4. **Time zones:** All timestamps are `timestamptz`. Use `AT TIME ZONE 'UTC'` for consistency.
5. **NULL system_type = regular chat:** 290K of 293K messages have NULL system_type (user/AI chat). Non-NULL: 'user-info' (2298), 'email-inbound' (568), 'ms-user-import-data' (84).
6. **Join path for conversion:** `users → users_subscriptions → subscriptions` gives conversion data. `users → sessions → session_messages` gives engagement data.
7. **Roles are in a separate table:** `users` does NOT have a `roles` column. Use `users_roles` table: `JOIN users_roles ur ON ur.parent_id = u.id WHERE ur.value = 'client'`. Most users are 'client'. Filter admin/api accounts by excluding them.
8. **Actual table names:** The dump uses `subscriptions_rels` (subscriptions-to-capabilities join), `users_roles` (user role assignments), `users_sessions` (login sessions). Some tables from the original schema (emails_to_emails, emails_attachments, session_messages_attachments, users_media) may not be in this dump.
8. **Row counts (actual):** users=1721, sessions=10670, session_messages=293422, emails=2436, users_subscriptions=1119, users_roles=1746, users_sessions=1997, subscriptions=10, subscription_capabilities=3, subscriptions_features=27, subscriptions_rels=25.
