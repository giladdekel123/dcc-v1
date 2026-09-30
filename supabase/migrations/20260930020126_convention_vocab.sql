-- KVL project convention vocabularies (inspired by ISO 19650 concepts; not an ISO code table).
-- Project-specific reference data (WBS, organisations, people) is loaded from the corpus spec.

insert into dcc.discipline (code, label, aliases) values
  ('G', 'General / project management', '{"general","project management","PM"}'),
  ('C', 'Highways and civil',           '{"highways","civil","road","pavement","earthworks"}'),
  ('D', 'Drainage',                     '{"drainage","surface water","SW","attenuation","pond","culvert"}'),
  ('S', 'Structures',                   '{"structures","structural","bridge","abutment"}'),
  ('T', 'Geotechnical',                 '{"geotechnical","geotech","ground investigation","GI","soils"}'),
  ('U', 'Utilities',                    '{"utilities","services","water main","diversion"}'),
  ('E', 'Environmental',                '{"environmental","ecology","landscaping"}'),
  ('Q', 'Commercial / quantity surveying', '{"commercial","QS","quantity surveying","cost"}');

insert into dcc.doc_type (code, label, aliases) values
  ('DR', 'Drawing',                   '{"drawing","dwg","plan","GA","general arrangement","section"}'),
  ('RP', 'Report',                    '{"report","study","assessment"}'),
  ('RI', 'Request for information',   '{"RFI","request for information","query","question"}'),
  ('LT', 'Letter',                    '{"letter","correspondence"}'),
  ('MM', 'Meeting minutes',           '{"minutes","meeting","MoM","progress meeting"}'),
  ('SB', 'Submittal',                 '{"submittal","submission","method statement","material approval"}'),
  ('BQ', 'Bill of quantities',        '{"BoQ","bill of quantities","quantities","pricing"}'),
  ('CT', 'Certificate / assurance',   '{"certificate","assurance","check certificate","Cat III"}'),
  ('SC', 'Schedule / register',       '{"schedule","register","programme","spreadsheet","tracker"}');

insert into dcc.stage (code, label, seq, aliases) values
  ('PD', 'Preliminary design', 1, '{"preliminary","outline design","concept"}'),
  ('DD', 'Detailed design',    2, '{"detailed design","detail design"}'),
  ('CN', 'Construction',       3, '{"construction","site","works"}'),
  ('HO', 'Handover',           4, '{"handover","completion","close-out"}');

insert into dcc.permitted_use (code, label) values
  ('information',   'Information only'),
  ('review',        'Review and comment'),
  ('approval',      'Submitted for approval'),
  ('construction',  'Construction / proceed with works'),
  ('as_built',      'As-built record'),
  ('not_permitted', 'Not to be used');

insert into dcc.status (code, label, permitted_use_code, aliases) values
  ('FI', 'For information',              'information',   '{"for information","info"}'),
  ('RV', 'For review and comment',       'review',        '{"for review","for comment"}'),
  ('AP', 'For approval',                 'approval',      '{"for approval","submitted"}'),
  ('AC', 'Accepted / approved',          'construction',  '{"accepted","approved"}'),
  ('AN', 'Approved with comments',       'construction',  '{"approved with comments","accepted with comments"}'),
  ('RJ', 'Rejected',                     'not_permitted', '{"rejected","not approved","resubmit"}'),
  ('FC', 'For construction',             'construction',  '{"for construction","IFC","issued for construction"}'),
  ('AB', 'As-built',                     'as_built',      '{"as-built","as built","record drawing"}'),
  ('OP', 'Open',                         'information',   '{"open","outstanding","awaiting response"}'),
  ('CL', 'Closed',                       'information',   '{"closed","answered","resolved"}'),
  ('IS', 'Issued',                       'information',   '{"issued","sent"}');
