# -*- encoding:utf-8 -*-



# A demo to show how to collect the suggestion words when we search with search engine

import urllib
import urllib3
import re
import time
from random import choice

wordsSearchingList = ['love', 'like', 'hate']

for item in wordsSearchingList:
	keyWord = urllib.quote(item)

	# url = 'https://www.google.co.jp/complete/search?client=hp&hl=zh-CN&gs_rn=48&gs_ri=hp&tok=9rRotU-cEDUkHKHgOoZAZw&cp=4&gs_id=je&q=%s&xhr=t' % (keyWord)
	url = 'https://www.google.com/complete/search?q=facebook%20a&cp=10&client=gws-wiz&xssi=t&hl=zh-CN&authuser=0&pq=python%E6%8A%93%E5%8F%96google%E6%90%9C%E7%B4%A2%E8%81%94%E6%83%B3%E8%AF%8D&psi=nuW_YvWLGpag1e8PnPeB8AI.1656743327097&gs_mss=python%E6%8A%93%E5%8F%96google%E6%90%9C%E7%B4%A2%E8%81%94%E6%83%B3%E8%AF%8D&dpr=1'
# 填写Request Headers，防止被ban掉
	headers = {
		"GET": url,
		"Host": "www.google.com",
		"Referer": "https://www.google.com/",
		"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/101.0.4951.54 Safari/537.36",
	}

	req = urllib3.Request(url)

	for key in headers:
		req.add_header(key, headers[key])

	html = urllib3.urlopen(req).read()

	# 正则匹配
	pattern = re.compile(r'"({searchWord}.*?)"'.format(searchWord = keyWord))
	results = pattern.findall(html)
	for item1 in results:
		print(item1)
	time.sleep(1)
	print('-------------------------------------')

