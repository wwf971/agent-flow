begin;

drop table if exists event cascade;
drop table if exists conversation cascade;
drop function if exists notify_conversation_update() cascade;

create table conversation (
  id bigint primary key,
  metadata jsonb not null default '{"evetList":[]}'::jsonb,
  isInTrashbin boolean not null default false,
  rankGlobal text,
  createAt timestamptz default now(),
  createAtTimezone smallint,
  updateAt timestamptz default now(),
  updateAtTimezone smallint,
  constraint conversation_metadata_is_object check (jsonb_typeof(metadata) = 'object'),
  constraint conversation_metadata_evet_list_is_array check (
    metadata ? 'evetList' and jsonb_typeof(metadata -> 'evetList') = 'array'
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
  on conversation(isInTrashbin, rankGlobal, updateAt desc, id desc);

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
begin
  if TG_TABLE_NAME = 'conversation' then
    conversation_id_text := NEW.id::text;
  elsif TG_OP = 'DELETE' then
    conversation_id_text := OLD.conversationId::text;
  else
    conversation_id_text := NEW.conversationId::text;
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
