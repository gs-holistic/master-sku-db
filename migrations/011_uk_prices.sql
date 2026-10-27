-- UK prices (GBP), set only from the G Pen Hub. With no UK price set, the API shows the US figure in pounds.
ALTER TYPE core.region ADD VALUE IF NOT EXISTS 'UK';
