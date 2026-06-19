begin;

drop table if exists event cascade;
drop table if exists subagent_run_child cascade;
drop table if exists subagent_run cascade;
drop table if exists conversation_iter_worker cascade;
drop table if exists conversation cascade;
drop function if exists notify_conversation_update() cascade;

create table conversation (
  id bigint primary key,
  metadata jsonb not null default '{"eventList":[]}'::jsonb,
  isInTrashbin boolean not null default false,
  rankGlobal text,
  parentId bigint references conversation(id) on delete cascade,
  version bigint not null default 0,
  stateCode integer not null default 100,
  execStatusCode integer not null default 0,
  leaseId text,
  leaseWorkerId text,
  leaseExpireAt timestamptz,
  leaseRetryCount integer not null default 0,
  leaseRetryAfterAt timestamptz,
  createAt timestamptz default now(),
  createAtTimezone smallint,
  updateAt timestamptz default now(),
  updateAtTimezone smallint,
  constraint conversation_metadata_is_object check (jsonb_typeof(metadata) = 'object'),
  constraint conversation_metadata_event_list_is_array check (
    metadata ? 'eventList' and jsonb_typeof(metadata -> 'eventList') = 'array'
  )
);

create table event (
  id bigint primary key,
  conversationId bigint not null references conversation(id) on delete cascade,
  typeCode integer,
  typeText text not null,
  subtypeCode integer,
  subtypeText text,
  contentType integer not null,
  contentText text,
  contentJson jsonb,
  metadata jsonb,
  createAt timestamptz default now(),
  createAtTimezone smallint,
  updateAt timestamptz default now(),
  updateAtTimezone smallint
);

create index conversation_update_at_idx
  on conversation(updateAt desc, id desc);

create index conversation_rank_global_idx
  on conversation(isInTrashbin, rankGlobal, updateAt desc, id desc)
  where parentId is null;

create index conversation_parent_idx
  on conversation(parentId, updateAt desc, id desc);

create index conversation_iter_pending_idx
  on conversation(stateCode, execStatusCode, leaseExpireAt, leaseRetryAfterAt, id)
  where stateCode < 0;

create index conversation_lease_expire_idx
  on conversation(leaseExpireAt, id)
  where leaseId is not null;

create table conversation_iter_worker (
  workerId text primary key,
  conversationId bigint,
  leaseId text,
  assignAt timestamptz,
  heartbeatAt timestamptz,
  updateAt timestamptz default now(),
  workerProcessId integer,
  workerHostText text,
  workerStartAt timestamptz
);

create index conversation_iter_worker_idle_idx
  on conversation_iter_worker(heartbeatAt, workerId)
  where conversationId is null;

create table subagent_run (
  runId text primary key,
  parentConversationId bigint not null references conversation(id) on delete cascade,
  requestEventId bigint not null references event(id) on delete cascade,
  startEventId bigint references event(id) on delete set null,
  resultEventId bigint references event(id) on delete set null,
  statusText text not null,
  childCount integer not null default 0,
  childTerminalCount integer not null default 0,
  childSuccessCount integer not null default 0,
  childFailureCount integer not null default 0,
  requestJson jsonb,
  createAt timestamptz default now(),
  updateAt timestamptz default now()
);

create table subagent_run_child (
  runId text not null references subagent_run(runId) on delete cascade,
  childConversationId bigint not null references conversation(id) on delete cascade,
  parentConversationId bigint not null references conversation(id) on delete cascade,
  childIndex integer not null,
  nameText text not null,
  statusText text not null,
  turnCount integer not null default 0,
  latestToolCallJson jsonb,
  returnJson jsonb,
  failureText text,
  createAt timestamptz default now(),
  updateAt timestamptz default now(),
  primary key (runId, childConversationId)
);

create index subagent_run_parent_idx
  on subagent_run(parentConversationId, updateAt desc, runId);

create index subagent_run_child_run_idx
  on subagent_run_child(runId, childIndex, childConversationId);

create index event_conversation_create_at_idx
  on event(conversationId, createAt, id);

create index event_type_text_idx
  on event(typeText, subtypeText);

create function notify_conversation_update()
returns trigger
language plpgsql
as $$
declare
  conversation_id_text text;
  parent_conversation_id_text text;
begin
  if TG_TABLE_NAME = 'conversation' and TG_OP = 'DELETE' then
    conversation_id_text := OLD.id::text;
    parent_conversation_id_text := OLD.parentId::text;
  elsif TG_TABLE_NAME = 'conversation' then
    conversation_id_text := NEW.id::text;
    parent_conversation_id_text := NEW.parentId::text;
  elsif TG_OP = 'DELETE' then
    conversation_id_text := OLD.conversationId::text;
    select parentId::text
    into parent_conversation_id_text
    from conversation
    where id = OLD.conversationId;
  else
    conversation_id_text := NEW.conversationId::text;
    select parentId::text
    into parent_conversation_id_text
    from conversation
    where id = NEW.conversationId;
  end if;

  perform pg_notify(
    'conversation_update',
    json_build_object(
      'typeText', 'conversationUpdate',
      'tableText', TG_TABLE_NAME,
      'operationText', TG_OP,
      'conversationId', conversation_id_text
    )::text
  );

  if parent_conversation_id_text is not null and parent_conversation_id_text <> conversation_id_text then
    perform pg_notify(
      'conversation_update',
      json_build_object(
        'typeText', 'conversationUpdate',
        'tableText', TG_TABLE_NAME,
        'operationText', TG_OP,
        'conversationId', parent_conversation_id_text
      )::text
    );
  end if;

  if TG_OP = 'DELETE' then
    return OLD;
  end if;
  return NEW;
end;
$$;

create trigger conversation_notify_update
after insert or update or delete on conversation
for each row execute function notify_conversation_update();

create trigger event_notify_update
after insert or update or delete on event
for each row execute function notify_conversation_update();

commit;
