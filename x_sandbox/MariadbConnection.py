import mysql.connector as mariadb

try:
    conn = mariadb.connect(user='bhs_rest', password='REST@bhs-db', database='bhs_test', host='192.168.1.5')

    cursor = conn.cursor()

    cursor.execute('select st_id, st_name from sensor_types order by st_id asc;')

     for (st_id, st_name) in cursor:
        print('ID: ' + str(st_id))
        print('name: ' + st_name)

except mariadb.Error as e:
    print('Something went terribly wrong: {}').format(e)

finally:
    cursor.close()
    conn.close()
