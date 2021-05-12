from airflow import DAG
from airflow.operators.python_operator import PythonOperator
from airflow.utils.trigger_rule import TriggerRule
from airflow.models import Variable
from airflow.hooks.S3_hook import S3Hook
from airflow.hooks.postgres_hook import PostgresHook

from datetime import datetime
from datetime import timedelta
import logging


log = logging.getLogger(__name__)


# =============================================================================
# 1. Set up the main configurations of the dag
# =============================================================================

default_args = {
    'start_date': datetime(2021, 3, 8),
    'owner': 'Airflow',
    'filestore_base': '/tmp/airflowtemp/',
    'email_on_failure': True,
    'email_on_retry': False,
    'aws_conn_id': "aws_default_carinatiedemann",
    'bucket_name': Variable.get("housing_web_scraping_pipeline", deserialize_json=True)['bucket_name'],
    'postgres_conn_id': 'engineering_groupwork_carina',
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
    'db_name': Variable.get("housing_db", deserialize_json=True)['db_name']
}

dag = DAG('housing_web_scraping_pipeline',
          description='Web scraping pipeline scraping housing data and saving output to a postgreQL db in RDS',
          schedule_interval='@weekly',
          catchup=False,
          default_args=default_args,
          max_active_runs=1)

# =============================================================================
# 2. Define different functions
# =============================================================================

# Creating schema if inexistant
def create_schema(**kwargs):
    pg_hook = PostgresHook(postgres_conn_id=kwargs['postgres_conn_id'], schema=kwargs['db_name'])
    conn = pg_hook.get_conn()
    cursor = conn.cursor()
    log.info('Initialised connection')
    sql_queries = """
    CREATE SCHEMA IF NOT EXISTS schema_housing;

    CREATE TABLE IF NOT EXISTS schema_housing.zoopla(
        "ad_id" numeric,
        "link" varchar(256),
        "price" numeric,
        "bedrooms" int,
        "bathrooms" int,
        "living_rooms" int,
        "distance" numeric,
        "address" varchar(256)
    );

    CREATE TABLE IF NOT EXISTS schema_housing.dexter(
        "ad_identification" numeric,
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

    DROP TABLE IF EXISTS schema_housing.googlemaps;
    CREATE TABLE schema_housing.googlemaps(

        "id" SERIAL PRIMARY KEY,
        "OSX" int,
        "OSY" int,
        "latitude" numeric,
        "longitude" numeric,
        "Zone" int,
        "Postcode" varchar(256),
        "subway_station" varchar(256)
    );

    DROP TABLE IF EXISTS schema_housing.air_quality;
    CREATE TABLE schema_housing.air_quality(

        "id" SERIAL PRIMARY KEY,
        "latitude" numeric,
        "longitude" numeric,
        "Zone" int,
        "air_quality_index" numeric,
        "subway_station" varchar(256)
    );
    """

    cursor.execute(sql_queries)
    conn.commit()
    log.info("Created Schema and Tables")

# Webscraping
def web_scraping_function_zoopla(**kwargs):
    import pandas as pd
    import numpy as np
    #import matplotlib.pyplot as plt
    import time
    from bs4 import BeautifulSoup #requires pip install
    import requests
    import re
    from re import sub
    from decimal import Decimal
    import io

    # Convert price string into a numerical value
    def to_num(price):
        value = Decimal(sub(r'[^\d.]', '', price))
        return float(value)

    def is_dropped(money):
        for i in range(len(money)):
            if(money[i] != '£' and money[i] != ',' and (not money[i].isdigit())):
                return True
        return False

    #set up the the scraper
    url = 'https://www.zoopla.co.uk/for-sale/property/london/?page_size=25&q=london&radius=0&results_sort=newest_listings&pn='

    map = {}
    id = 0

    #set max_pages to 2 for test purposes
    max_pages = 2



    for p in range(max_pages):
        cur_url = url + str(p + 1)

        print("Scraping page: %d" % (p + 1))
        #print(cur_url)
        html_text = requests.get(cur_url).text
        soup = BeautifulSoup(html_text, 'lxml')

        ads = soup.find_all('div', class_ = 'css-wfndrn-StyledContent e2uk8e18')
        page_nav = soup.find_all('a', class_ = 'css-slm4qd-StyledPaginationLink eaoxhri5')

        if(len(page_nav) == 0):
            print("max page number: %d" % (p))
            end = time.time()
            print(end - start)
            break

        for k in range(len(ads)):
            ad = ads[k]

            #find link and ID ('identifier' in the link acts as a unique id for the ad)
            link = ad.find('a', class_ = 'e2uk8e4 css-gl9725-StyledLink-Link-FullCardLink e33dvwd0')

            #find section for address
            address = ad.find('p', class_ = 'css-wfe1rf-Text eczcs4p0').text

            #find price information
            price = ad.find('p', class_ = 'css-18tfumg-Text eczcs4p0').text

            # if the price is valid or not, if not we do not consider this ad
            if(is_dropped(price)): continue

            #find public transport information
            subway_section = ad.find('div', class_ = 'css-braguw-TransportWrapper e2uk8e28')
            subway_information = subway_section.find_all('p', class_ = 'css-wfe1rf-Text eczcs4p0')

            #skip ads that only contain information of train station
            outlier = subway_section.find('span', class_ = 'e1uy4ban0 css-10ibqwe-StyledIcon-Icon e15462ye0')
            if(outlier['data-testid'] == 'national_rail_station'): continue

            #find section for bedroom, bathroom and living room information (room numbers)
            feature_section = ad.find('div', class_ = 'css-58bgfg-WrapperFeatures e2uk8e15')

            #find all information available for room numbers
            category = feature_section.find_all('div', class_ = 'ejjz7ko0 css-l6ka86-Wrapper-IconAndText e3e3fzo1')

            #assign id
            ad_id = link['href'] #returns url snippet with identifier from the url
            ad_id= ad_id.split("?")[0] #split by '?' ans '/' and apply index to retain only identifier number
            ad_id= ad_id.split("/")[3]

            if(ad_id in map): continue
            map[ad_id] = {}

            #assign link
            link = 'https://www.zoopla.co.uk/' + link['href']
            map[ad_id]["link"] = link

            #assign address
            map[ad_id]["address"] = address

            #assign bedroom nr
            try:
                map[ad_id]["room_nr"] = category[0].text
            except IndexError:
            #insert None value if index is not found
                map[ad_id]["room_nr"] = 'None'
                #print("Feature not listed")

            #assign bathroom nr
            try:
                map[ad_id]["bath_nr"] = category[1].text
            except IndexError:
            #insert None value if index is not found
                map[ad_id]["bath_nr"] = 'None'
                #print("Feature not listed")

            #assign living room nr
            try:
                map[ad_id]["living_nr"] = category[2].text
            except IndexError:
            #insert None value if index is not found
                map[ad_id]["living_nr"] = 'None'
                #print("Feature not listed")

            #assign price
            map[ad_id]["price"] = to_num(price)

            #assign subway station and distance to it
            s = subway_information[0].text
            x = s.split(' miles ')
            if len(x) == 1: continue
            map[ad_id]["distance"] = float(x[0])
            map[ad_id]["subway_station"] = x[1]

    print("Scraping task finished")

    #transform to dict to list
    result = []
    cur_row = 0
    for cur_id in map.keys():
        link = map[cur_id]["link"]
        cur_price = map[cur_id]["price"]
        cur_bedroom = map[cur_id]["room_nr"]
        cur_bathroom = map[cur_id]["bath_nr"]
        cur_living = map[cur_id]["living_nr"]
        cur_address = map[cur_id]["address"]
        cur_distance = map[cur_id]["distance"]
        cur_subway_station = map[cur_id]["subway_station"]
        result.append([])
        result[cur_row].append(str(cur_id))
        result[cur_row].append(str(link))
        result[cur_row].append(str(cur_price))
        result[cur_row].append(str(cur_bedroom))
        result[cur_row].append(str(cur_bathroom))
        result[cur_row].append(str(cur_living))
        result[cur_row].append(str(cur_address))
        result[cur_row].append(str(cur_distance))
        result[cur_row].append(str(cur_subway_station))
        cur_row += 1

    #transform to dataframe
    df = pd.DataFrame(result, columns = ["ad_id", "link", "price", "bedrooms", "bathrooms", "living_rooms", "address", "distance", "subway_station"])
    df

    #Adjusting "None values to be NaN for df
    df = df.replace(r'None', np.NaN)
    # df = df.where(pd.notnull(df), None)
    log.info("Scraping succesful")


    #Establishing S3 connection
    s3 = S3Hook(kwargs['aws_conn_id'])
    bucket_name = kwargs['bucket_name']
    #name of the file
    key = Variable.get("housing_webscraping_get_csv", deserialize_json=True)['key2']

    # Prepare the file to send to s3
    csv_buffer_zoopla = io.StringIO()
    #Ensuring the CSV files treats "NAN" as null values
    zoopla_csv=df.to_csv(csv_buffer_zoopla, index=False)

    # Save the pandas dataframe as a csv to s3
    s3 = s3.get_resource_type('s3')

    # Get the data type object from pandas dataframe, key and connection object to s3 bucket
    data = csv_buffer_zoopla.getvalue()

    print("Saving CSV file")
    object = s3.Object(bucket_name, key)

    # Write the file to S3 bucket in specific path defined in key
    object.put(Body=data)

    log.info('Finished saving the scraped data to s3')

    return



def web_scraping_function_dexter(**kwargs):

        # Import packages
        import pandas as pd
        import numpy as np
        import datetime
        from bs4 import BeautifulSoup #requires pip install
        import requests #requires pip install
        import re
        import time

        import io
        # document time
        time_started = str(datetime.datetime.now()).replace(" ","_").replace(":","-")[0:19]
        ## Define list of subway stations
        Underground_lines = ['Bakerloo', 'Central', 'Circle', 'District', 'DLR', 'Hammersmith & City',
                         'Jubilee', 'Metropolitan', 'Northern', 'Piccadilly', 'Victoria', 'Waterloo & City']

        ## Function to extract characteristics on each ad from the main webpage
        def feature_extract(html_text):

            soup = BeautifulSoup(html_text, 'lxml')

            ## Parse for the different divisions within the add

            # ads = soup.find_all('div', class_ = 'result-content') #searches for 'div' and is filtered by the CSS-snippet
            ads = soup.find_all('li', class_ = 'result item for-sale infinite-item')#searches for 'div' and is filtered by the CSS-snippet
            ## Set-up for the loop
            results = {} #create nested dictionary to store the results
            id_ad = 0 #insert ad_ID to distinguish between each ad

            ## Loop across all ads
            for k in range(len(ads)):
                ad = ads[k]
                id_ad += 1
                results[id_ad] = {}

                ## Extracting features from the ad
                name = ad.find('h3').a.contents[0]
                try:
                    price = ad.find('span', class_ = 'price-qualifier').text #catches the price WITHIN one ad
                except:
                    continue
                address = ad.find('span', class_ = 'address-area-post').text

                # Number of bedrooms extracted from string
                try:
                    bedrooms = ad.find('li', class_ = 'Bedrooms').text
                except:
                    continue
                bedrooms_nbr = int(bedrooms.split()[0])

                # Number of bedrooms extracted from string
                bathrooms_str = str(ad.find('li',class_ = 'Bathrooms'))
                bathrooms_nbr = re.findall(r'\d+', bathrooms_str)
                bathrooms_nbr2 = int(bathrooms_nbr[0] if len(bathrooms_nbr)!= 0  else 0)

                # Number of bedrooms extracted from string
                reception_str = str(ad.find('li',class_ = 'Receptions'))
                reception_nbr = re.findall(r'\d+', reception_str)
                reception_nbr2 = int(reception_nbr[0] if len(reception_nbr)!= 0  else 1)

                link = ad.find('h3').a.get("href")

                ad_identification = ads[k]['data-property-id']

                # Create dictionary of results per ad id
                results[id_ad]['ad_identification'] = ad_identification
                results[id_ad]["street_name"] = name
                results[id_ad]["price"] = price
                results[id_ad]["address"] = address
                results[id_ad]["bedrooms"] = bedrooms_nbr
                results[id_ad]["bathrooms"] = bathrooms_nbr2
                results[id_ad]["reception"] = reception_nbr2
                results[id_ad]["link"] = ("https://www.dexters.co.uk" + link)

                # Create dataframe from dictionary of results
                df_houses = pd.DataFrame.from_dict(results, orient='index')

            return df_houses

        ## Function to create list of pages base on url and number of iterations desired
        def page_list(string, iterations):
            pages_list = []
            for i in range(iterations):
                pages_list.append(string + str(i+1))

            return pages_list

        ## Function to get the maximum number of listing on Dexter's website
        def page_max(url):
            html_text = requests.get(url).text
            soup = BeautifulSoup(html_text, 'lxml')
            amount = soup.find('span', class_ = 'marker-count has-results').text
            amount_num = re.sub('\D', '', amount)
            return int(amount_num)

        ## Function to launch scrapper on a specific webpage with number of pages to scrap
        def pages_scrap(main_page, iter_page, pages):
            max_pages = (page_max(main_page)/18)
            list_of_pages = page_list(iter_page, pages) # Create list of pages to scrape
            df_list = [] #Create list of dataframes to be concatenated by the end of the loop

            # Loop through all pages to create the different dataframes
            for page in list_of_pages:
                html_page = requests.get(page)
                html_page.encoding = 'utf-8'
                page = html_page.text
                df_ads = feature_extract(page)
                df_list.append(df_ads)

            # Concatenate the different dataframes
            df_results = pd.concat(df_list)
            df_results = df_results.drop_duplicates()
            df_results = df_results.reset_index(drop=True)

            print('Remaining number of page: ', int(max_pages - pages) )

            return df_results
        # 1.2 Subway related functions

        ## Function to extract subway info list from a house webpage on dexter
        def get_info_subway(link):
            html_text = requests.get(link).text
            soup = BeautifulSoup(html_text, 'lxml')
            subway = soup.find('ul', class_ = 'list-information').text

            return subway

        ## Function to get list of values for subway distances with string
        def sub_values(string):
            split = string.split('\n')
            list_1 = list(filter(None, split))

            list_2 = []
            for i in list_1:
                x = i.split('-')
                list_2.append(x)

            list_3 = [item.strip() for sublist in list_2 for item in sublist]
            list_4 = list_3[0:3]

            return list_3

        ## Function to get the closest stop on the tube if any
        def closest_line(list_of_lines):
            j = 0
            nearby_data = []
            for i in range(len(list_of_lines)):
                if list_of_lines[i] == 'London Underground' or list_of_lines[i] in Underground_lines and (j != 1 and i!=0):
                    if (' ' in list_of_lines[i-2]) == False :
                        nearby_data.append(list_of_lines[i-3])
                        nearby_data.append(list_of_lines[i-2])
                        nearby_data.append(list_of_lines[i-1])
                        nearby_data.append(list_of_lines[i])
                        j = 1

                        nearby_data[0] = (' '.join(nearby_data[0:2]))
                        del nearby_data[1]

                    else:
                        nearby_data.append(list_of_lines[i-2])
                        nearby_data.append(list_of_lines[i-1])
                        nearby_data.append(list_of_lines[i])
                        j = 1

            return nearby_data

        ## Function to populate datafrmae with closest tube stop name, distance, and related tube line
        def subway_per_house(df):
            #Create new empty (NaN) columns in the existing dataframe
            df = df.reindex(columns = df.columns.tolist() + ['subway_station','distance','tube_line'])

            #Loop through all lines of dataframe
            for i in range(len(df)):
                x = df['link'].iloc[i] #Get link of house page to scrape
                subs = get_info_subway(x) #Extract tube line info
                subs_2 = sub_values(subs) #Get list of subway station and distance
                subs_3 = closest_line(subs_2) #Extract closest tube station only

                # Populate dataframe if a tubeway station has been found or not
                if len(subs_3)!= 0:
                    df['subway_station'].iloc[i] = subs_3[0]
                    df['distance'].iloc[i] = subs_3[1]
                    df['tube_line'].iloc[i] = subs_3[2]
                else:
                    df['subway_station'].iloc[i] = np.NaN
                    df['distance'].iloc[i] = np.NaN
                    df['tube_line'].iloc[i] = np.NaN

            df = df.astype(str)

            return df

        #Functions to clean subway output
        def get_tube_dist(string):
            string_m = string.split(' ')
            num_val = string_m[-1]

            return num_val
        def strip_tube(string):
            string_m = string.split(' ')
            string_m = string_m[:-1]
            string_m = ' '.join(string_m)

            return string_m
        def hasNumbers(inputString):
            return any(char.isdigit() for char in inputString)

        ## Function to clean subway stops when too many words in the string
        def clean_tube_stop_string(string):
            forbiddden_words = ['London Overground', 'Railway', 'Network Rail', 'Tramlink']
            count_forbidden = 0

            for j in forbiddden_words:
                if count_forbidden == 0:
                    if j in string:
                        string_update = string.split()[-1]
                        count_forbidden = 1
                    else:
                        string_update = string

            return(string_update)

        ## Function to input tube distance into the right column when value is in 'tube_stop'
        def clean_tube_dist(df):
            df['distance'] = df['distance'].astype('str')

            errors  = df[df.loc[:, 'distance'].map(hasNumbers) == False].copy()
            errors_2 = errors.loc[errors['subway_station'] != 'NaN'].copy()
            errors_2.loc[:, 'distance'] = errors_2.loc[:, 'subway_station'].map(get_tube_dist)
            errors_2.loc[:, 'subway_station'] = errors_2.loc[:, 'subway_station'].map(strip_tube)
            errors_2

            #Create copy of original df for modification
            df_copy = df.copy()

            # replace values in final df
            for i in errors_2.index:
                df_copy.loc[i] = errors_2.loc[i]

            return df_copy

        ## Functions to deal with Victoria tube stops (Victoria being both a tube stop and a tube line)
        def victoria_clean_stop(string):
            str_vic = 'Victoria'
            str_check = string.split()
            if str_check[0] == 'Victoria':
                str_return = str_check[1]
            else:
                str_return = str_vic

            return str_return
        def clean_tube_victoria(df):
            df['subway_station'] = df['subway_station'].astype('str')

            errors  = df[df['subway_station'].str.contains('Victoria')].copy()

            errors.loc[:, 'subway_station'] = errors.loc[:, 'subway_station'].map(victoria_clean_stop)

            #Create copy of original df for modification
            df_copy = df.copy()

            # Replace values in final df
            for i in errors.index:
                df_copy.loc[i] = errors.loc[i]

            return df_copy

        ## Final cleaning function to apply previous cleaning on 'tube_stop' and 'tube_dist' for the whole dataframe
        def clean_tube_stop(df):
            df_2 = df.copy()
            df_2 = clean_tube_dist(df_2)
            df_2['subway_station'] = df_2['subway_station'].astype('str')
            df_2['subway_station'] = df_2['subway_station'].map(clean_tube_stop_string)

            df_2 = clean_tube_victoria(df_2)
            # #Keep the ID of the add as index or not


            return df_2

        dexter_list_1 = pages_scrap('https://www.dexters.co.uk/property-sales/properties-for-sale-in-london',
                                    'https://www.dexters.co.uk/property-sales/properties-for-sale-in-london/page-', 50)


        ## Fetch subway related information from the previous dataframe
        output_list = subway_per_house(dexter_list_1)

        output_list

        cleaned = clean_tube_stop(output_list)
        cleaned

        #Cleaning the price and distance variables and converting to float
        cleaned['price'] = cleaned['price'].str.replace('£', '')
        cleaned['price'] = cleaned['price'].str.replace(',', '').astype(float)
        cleaned['distance'] = cleaned['distance'].str.replace('m', '').astype(float)


        cleaned['subway_station'].nunique()
        cleaned_dict = cleaned.to_dict(orient='records')

        log.info('Finished scraping the data')
        #create connection for uploading the file to S3

        #Establishing S3 connection
        s3 = S3Hook(kwargs['aws_conn_id'])
        bucket_name = kwargs['bucket_name']
        #name of the file
        key = Variable.get("housing_webscraping_get_csv", deserialize_json=True)['key1']

        # Prepare the file to send to s3
        csv_buffer = io.StringIO()
        #Ensuring the CSV files treats "NAN" as null values
        cleaned_csv=cleaned.to_csv(csv_buffer, index=False)

        # Save the pandas dataframe as a csv to s3
        s3 = s3.get_resource_type('s3')

        # Get the data type object from pandas dataframe, key and connection object to s3 bucket
        data = csv_buffer.getvalue()

        print("Saving Parquet file")
        object = s3.Object(bucket_name, key)

        # Write the file to S3 bucket in specific path defined in key
        object.put(Body=data)

        log.info('Finished saving the scraped data to s3')


        return cleaned_dict



# Saving file to postgreSQL database
def save_result_to_postgres_db_zoopla(**kwargs):

    import pandas as pd
    import io

    #Establishing connection to S3 bucket
    bucket_name = kwargs['bucket_name']
    key = Variable.get("housing_webscraping_get_csv", deserialize_json=True)['key2']
    s3 = S3Hook(kwargs['aws_conn_id'])
    log.info("Established connection to S3 bucket")


    # Get the task instance
    task_instance = kwargs['ti']
    print(task_instance)


    # Read the content of the key from the bucket
    csv_bytes_zoopla = s3.read_key(key, bucket_name)
    # Read the CSV
    clean_zoopla = pd.read_csv(io.StringIO(csv_bytes_zoopla ))#, encoding='utf-8')

    log.info('passing data from S3 bucket')

    # Connect to the PostgreSQL database
    pg_hook = PostgresHook(postgres_conn_id=kwargs["postgres_conn_id"], schema=kwargs['db_name'])
    conn = pg_hook.get_conn()
    cursor = conn.cursor()

    log.info('Initialised connection')

    #Required code for clearing an error related to int64
    import numpy
    from psycopg2.extensions import register_adapter, AsIs
    def addapt_numpy_float64(numpy_float64):
        return AsIs(numpy_float64)
    def addapt_numpy_int64(numpy_int64):
        return AsIs(numpy_int64)
    register_adapter(numpy.float64, addapt_numpy_float64)
    register_adapter(numpy.int64, addapt_numpy_int64)

    log.info('Loading row by row into database')
    # #Removing NaN values and converting to NULL:

    clean_zoopla = clean_zoopla.where(pd.notnull(clean_zoopla), None)

    #Load the rows into the PostgresSQL database
    s = """INSERT INTO schema_housing.zoopla( ad_id, link, price, bedrooms, bathrooms, living_rooms, distance, address) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"""
    for index in range(len(clean_zoopla)):
        obj = []

        obj.append([clean_zoopla.ad_id[index],
                   clean_zoopla.link[index],
                   clean_zoopla.price[index],
                   clean_zoopla.bedrooms[index],
                   clean_zoopla.bathrooms[index],
                   clean_zoopla.living_rooms[index],
                   clean_zoopla.distance[index],
                   clean_zoopla.address[index]])

        cursor.executemany(s, obj)
        conn.commit()

    log.info('Finished saving the scraped data to postgres database')

# Saving Dexter file to postgreSQL database
def save_result_to_postgres_db_dexter(**kwargs):

    import pandas as pd
    import io

    #Establishing connection to S3 bucket
    bucket_name = kwargs['bucket_name']
    key = Variable.get("housing_webscraping_get_csv", deserialize_json=True)['key1']
    s3 = S3Hook(kwargs['aws_conn_id'])
    log.info("Established connection to S3 bucket")


    # Get the task instance
    task_instance = kwargs['ti']
    print(task_instance)


    # Read the content of the key from the bucket
    csv_bytes = s3.read_key(key, bucket_name)
    # Read the CSV
    clean_dexter = pd.read_csv(io.StringIO(csv_bytes ))#, encoding='utf-8')

    log.info('passing data from S3 bucket')

    # Connect to the PostgreSQL database
    pg_hook = PostgresHook(postgres_conn_id=kwargs["postgres_conn_id"], schema=kwargs['db_name'])
    conn = pg_hook.get_conn()
    cursor = conn.cursor()

    log.info('Initialised connection')

    #Required code for clearing an error related to int64
    import numpy
    from psycopg2.extensions import register_adapter, AsIs
    def addapt_numpy_float64(numpy_float64):
        return AsIs(numpy_float64)
    def addapt_numpy_int64(numpy_int64):
        return AsIs(numpy_int64)
    register_adapter(numpy.float64, addapt_numpy_float64)
    register_adapter(numpy.int64, addapt_numpy_int64)

    log.info('Loading row by row into database')
    # #Removing NaN values and converting to NULL:

    clean_dexter = clean_dexter.where(pd.notnull(clean_dexter), None)

    #Load the rows into the PostgresSQL database
    s = """INSERT INTO schema_housing.dexter( ad_identification, street_name, price, address, bedrooms, bathrooms, reception, link, subway_station, distance, tube_line) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""
    for index in range(len(clean_dexter)):
        obj = []

        obj.append([clean_dexter.ad_identification[index],
                   clean_dexter.street_name[index],
                   clean_dexter.price[index],
                   clean_dexter.address[index],
                   clean_dexter.bedrooms[index],
                   clean_dexter.bathrooms[index],
                   clean_dexter.reception[index],
                   clean_dexter.link[index],
                   clean_dexter.subway_station[index],
                   clean_dexter.distance[index],
                   clean_dexter.tube_line[index]])

        cursor.executemany(s, obj)
        conn.commit()

    log.info('Finished saving the scraped data to postgres database')


#Alternative version for loading the data onto the POstgresSQL database via XCOM_PULL
# def s3_save_file_func(**kwargs):
#
#     import pandas as pd
#     import io
#
#     bucket_name = kwargs['bucket_name']
#     key = "housing_scraper_dexter.parquet"
#     key = kwargs['key']
#     s3 = S3Hook(kwargs['aws_conn_id'])
#
#     # Get the task instance
#     task_instance = kwargs['ti']
#
#     # Get the output of the bash task
#     scraped_data_previous_task_csv = task_instance.xcom_pull(task_ids="web_scraping_task_dexter")
#
#     log.info('xcom from web_scraping_task_dexter:{0}'.format(scraped_data_previous_task))
#     clean_zoopla = pd.DataFrame.from_dict(scraped_data_previous_task)
#
#     # Load the list of dictionaries with the scraped data from the previous task into a pandas dataframe
#     log.info('Loading scraped data into pandas dataframe')
#
#     log.info('Saving scraped data to {0}'.format(key))
#
#     # Prepare the file to send to s3
#     csv_buffer = io.StringIO()
#     clean_zoopla.to_csv(csv_buffer, index=False)
#
#     # Save the pandas dataframe as a csv to s3
#     s3 = s3.get_resource_type('s3')
#
#     # Get the data type object from pandas dataframe, key and connection object to s3 bucket
#     data = csv_buffer.getvalue()
#
#     print("Saving CSV file")
#     object = s3.Object(bucket_name, key)
#
#     # Write the file to S3 bucket in specific path defined in key
#     object.put(Body=data)
#
#     log.info('Finished saving the scraped data to s3')

# =============================================================================
# 3. Set up the main configurations of the dag
# =============================================================================
create_schema = PythonOperator(
    task_id='create_schema',
    python_callable=create_schema,
    op_kwargs=default_args,
    provide_context=True,
    dag=dag,
)
web_scraping_task_zoopla = PythonOperator(
    task_id='web_scraping_function_zoopla',
    provide_context=True,
    python_callable=web_scraping_function_zoopla,
    op_kwargs=default_args,
    dag=dag,

)

web_scraping_task_dexter = PythonOperator(
    task_id='web_scraping_task_dexter',
    provide_context=True,
    python_callable=web_scraping_function_dexter,
    op_kwargs=default_args,
    dag=dag,

)
save_result_to_postgres_db_zoopla = PythonOperator(
    task_id='save_result_to_postgres_db_zoopla',
    provide_context=True,
    python_callable=save_result_to_postgres_db_zoopla,
    trigger_rule=TriggerRule.ALL_SUCCESS,
    op_kwargs=default_args,
    dag=dag,

)

save_result_to_postgres_db_dexter = PythonOperator(
    task_id='save_result_to_postgres_db_dexter',
    provide_context=True,
    python_callable=save_result_to_postgres_db_dexter,
    trigger_rule=TriggerRule.ALL_SUCCESS,
    op_kwargs=default_args,
    dag=dag,

)
#Will work with the Alternative xcom_pull method
# s3_save_file_func = PythonOperator(
#     task_id='s3_save_file_func',
#     provide_context=True,
#     python_callable=s3_save_file_func,
#     trigger_rule=TriggerRule.ALL_SUCCESS,
#     op_kwargs=default_args,
#     dag=dag,
# )

# =============================================================================
# 4. Indicating the order of the dags
# =============================================================================

create_schema >> web_scraping_task_zoopla >> save_result_to_postgres_db_zoopla
create_schema >> web_scraping_task_dexter >> save_result_to_postgres_db_dexter
#For Alternative method
# create_schema >> web_scraping_task_dexter >> s3_save_file_func
