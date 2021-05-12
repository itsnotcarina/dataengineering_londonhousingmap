
    CREATE SCHEMA IF NOT EXISTS schema_housing;

    DROP TABLE schema_housing.zoopla;
    CREATE TABLE IF NOT EXISTS schema_housing.zoopla(
        "ad_id" numeric,
        "link" varchar(256),
        "price" numeric,
        "bedrooms" numeric,
        "bathrooms" numeric,
        "living_rooms" numeric,
        "address" varchar(256),
        "distance" numeric,
        "subway_station" varchar(256)
    );

    DROP TABLE schema_housing.dexters;
    CREATE TABLE IF NOT EXISTS schema_housing.dexters(
        "ad_id" numeric,
        "street_name" varchar(256),
        "price" numeric,
        "address" varchar(256),
        "bedrooms" numeric,
        "bathrooms" numeric,
        "reception" numeric,
        "link" varchar(256),
        "subway_station" varchar(256),
        "distance" numeric,
        "tube_line" varchar(256)

    );
    DROP TABLE schema_housing.location_information;
    CREATE TABLE IF NOT EXISTS schema_housing.location_information(

        "subway_station" varchar(256),
        "tube_line" varchar(256),
        "transport_zone" varchar(256),
        "address" varchar(256),
        "longitude" numeric,
        "latitude" numeric

    );

    DROP TABLE schema_housing.air_quality;
    CREATE TABLE IF NOT EXISTS schema_housing.air_quality(

        "site_code" varchar(256),
        "measurement_date_gmt" varchar(256),
        "species_code" varchar(256),
        "value" numeric
    );

    DROP TABLE schema_housing.tube_site_mapping;
    CREATE TABLE IF NOT EXISTS schema_housing.tube_site_mapping(

        "subway_station" varchar(256),
        "site_code" varchar(256)
    );

    DROP TABLE schema_housing.station_names_mapping;
    CREATE TABLE IF NOT EXISTS schema_housing.station_names_mapping(

        "location_information_station_names" varchar(256),
        "zoopla_scraper_station_names" varchar(256),
        "dexters_scraper_station_names" varchar(256)
    );
