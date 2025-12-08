import time
import uuid
import requests
import hashlib
import base64
import urllib

partnerID = 'Y7hHmkqf'  # 此处替换为您在丰桥平台获取的顾客编码!
checkword = 'ehpA2SxjBT0M0QY74VktZbPSx41xO9gt'  # 此处替换为您在丰桥平台获取的校验码!

reqURL = 'https://sfapi-sbox.sf-express.com/std/service'
# reqURL = 'https://sfapi.sf-express.com/std/service' #生产url

serviceCode = "EXP_RECE_CREATE_ORDER"
filePath = './callExpressRequest/01.order.json' # 下订单

# serviceCode = "EXP_RECE_SEARCH_ORDER_RESP"
# filePath = './callExpressRequest/02.order.query.json' # 订单结果查询

# serviceCode = "EXP_RECE_UPDATE_ORDER"
# filePath = './callExpressRequest/03.order.confirm.json' # 订单确认取消

# serviceCode = "EXP_RECE_FILTER_ORDER_BSP"
# filePath = './callExpressRequest/04.order.filter.json' # 订单筛选	

# serviceCode = "EXP_RECE_SEARCH_ROUTES"
# filePath = './callExpressRequest/05.route_query_by_MailNo.json' # 路由查询-通过运单号
# filePath = './callExpressRequest/05.route_query_by_OrderNo.json' # 路由查询-通过订单号 

# serviceCode = "EXP_RECE_GET_SUB_MAILNO"
# filePath = './callExpressRequest/07.sub.mailno.json' # 子单号申请

# serviceCode = "EXP_RECE_QUERY_SFWAYBILL"
# filePath = './callExpressRequest/09.waybills_fee.json' # 清单运费查询

# serviceCode = "EXP_RECE_REGISTER_ROUTE"
# filePath = './callExpressRequest/12.register_route.json' # 路由注册

# serviceCode = "EXP_RECE_CREATE_REVERSE_ORDER"
# filePath = './callExpressRequest/13.reverse_order.json' # 退货下单

# serviceCode = "EXP_RECE_CANCEL_REVERSE_ORDER"
# filePath = './callExpressRequest/14.cancel_reverse_order.json' # 退货消单
	
# serviceCode = "EXP_RECE_DELIVERY_NOTICE"
# filePath = './callExpressRequest/15.delivery_notice.json' # 派件通知
 
# serviceCode = "EXP_RECE_REGISTER_WAYBILL_PICTURE"
# filePath = './callExpressRequest/16.register_waybill_picture.json' # 图片注册及推送

# serviceCode = "EXP_RECE_WANTED_INTERCEPT"
# filePath = './callExpressRequest/18.wanted_intercept.json' # 截单转寄

# serviceCode = "EXP_RECE_QUERY_DELIVERTM"
# filePath = './callExpressRequest/19.query_delivertm.json' # 截单转寄

# serviceCode = "COM_RECE_CLOUD_PRINT_WAYBILLS"
# filePath = './callExpressRequest/20.cloud_print_waybills.json' # 云打印面单打印

#serviceCode = "EXP_RECE_UPLOAD_ROUTE"
#filePath = './callExpressRequest/21.upload_route.json' # 路由上传

# serviceCode = "EXP_RECE_SEARCH_PROMITM"
# filePath = './callExpressRequest/22.search_promitm.json' # 预计派送时间

# serviceCode = "EXP_EXCE_CHECK_PICKUP_TIME"
# filePath = './callExpressRequest/23.check_pickup_time.json' # 揽件服务时间

#serviceCode = "EXP_RECE_VALIDATE_WAYBILLNO"
#filePath = './callExpressRequest/24.validate_waybillno.json' # 运单号合法性校验
	
    


# 打开相应请求报文txt文件
file = open(filePath, 'r', encoding='utf8')
msgData = file.read()
# 关闭打开的文件
file.close()

requestID = uuid.uuid1() #生成uuid

timestamp = str(int(time.time())) #获取时间戳


def callSfExpressServiceByCSIM(reqURL, partnerID, requestID, serviceCode, timestamp, msgData, checkword):
    str = urllib.parse.quote_plus(msgData + timestamp + checkword)
    # 先md5加密然后base64加密
    m = hashlib.md5()    
    m.update(str.encode('utf-8'))       
    md5Str = m.digest()    
    msgDigest = base64.b64encode(md5Str).decode('utf-8')
    print("msgDigest: " + msgDigest)
    data = {"partnerID": partnerID,"requestID": requestID,"serviceCode": serviceCode,"timestamp": timestamp,"msgDigest": msgDigest,"msgData": msgData}
    # 发送post请求
    res = requests.post(reqURL, data=data)
    return res.text


print('请求报文：' + msgData)
respJson = callSfExpressServiceByCSIM(reqURL, partnerID, requestID, serviceCode, timestamp, msgData, checkword)
if respJson != '':
    print("--------------------------------------")
    print("返回报文: " + respJson)
    print("--------------------------------------")
    



    