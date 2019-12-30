import scrapy
import os

# ====== Config section ======
email = 'YOUR_NSUTS_EMAIL'
password = 'YOUR_NSUTS_PASSWORD'
olympiad_id = 176
output_dir = './output'
# ==== END Config section ====


class NSUtsSpider(scrapy.Spider):
    name = 'NSUts'
    start_urls = ['http://fresh.nsuts.ru/nsuts-new/login.cgi']
    queue = []

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        spider = super(NSUtsSpider, cls).from_crawler(crawler, *args, **kwargs)
        crawler.signals.connect(spider.idle, signal=scrapy.signals.spider_idle)
        return spider

    def parse(self, response):
        return scrapy.FormRequest.from_response(
            response,
            formdata={"email": email, "password": password},
            callback=self.after_login
        )

    @staticmethod
    def authentication_failed(response):
        return not response.url.startswith(
            'http://fresh.nsuts.ru/nsuts-new/select_olympiad.cgi'
        )

    def after_login(self, response):
        if self.authentication_failed(response):
            self.logger.error("Login failed")
            return

        yield scrapy.Request(
            'http://fresh.nsuts.ru/nsuts-new/select_olympiad.cgi?olympiad=' + str(olympiad_id),
            callback=self.after_olympiad_selected
        )

    def after_olympiad_selected(self, _):
        yield scrapy.Request(
            'http://fresh.nsuts.ru/nsuts-new/select_tour.cgi',
            callback=self.parse_tours_list
        )

    def parse_tours_list(self, response):
        for tour in response.css('table#tours > tr:not([id=\'top\']) > td:first-child > a'):
            self.queue.append(
                response.url + tour.css('::attr("href")').get()
            )

    def idle(self):
        self.crawler.engine.crawl(self.process_queue(), self)

    def process_queue(self):
        if not self.queue:
            return
        tour_url = self.queue.pop()
        return scrapy.Request(
            tour_url,
            callback=self.handle_redirect
        )

    def handle_redirect(self, _):
        yield scrapy.Request(
            "http://fresh.nsuts.ru/nsuts-new/news.cgi",
            callback=self.parse_tour,
            dont_filter=True
        )

    def parse_tour(self, response):
        left_container = response.css('div#left_container')
        tour_name = left_container.css('h1.section::text').get()
        tasks_url = 'http://fresh.nsuts.ru/nsuts-new/' + \
                    left_container.css('a::attr("href")').get()

        dir_path = os.path.join(output_dir, tour_name)
        os.makedirs(dir_path, exist_ok=True)

        yield scrapy.Request(
            tasks_url,
            callback=self.save_pdf,
            cb_kwargs={'dir_path': dir_path}
        )

    def save_pdf(self, response, dir_path):
        path = os.path.join(dir_path, "Условия задач.pdf")
        with open(path, 'wb') as f:
            f.write(response.body)
        yield scrapy.Request(
            "http://fresh.nsuts.ru/nsuts-new/report.cgi",
            callback=self.parse_submits,
            cb_kwargs={'dir_path': dir_path},
            dont_filter=True
        )

    def parse_submits(self, response, dir_path):
        left_container = response.css('div#left_container')
        acc_submits = left_container.css(
            'h1[id^="task"]::text, table[id^="submit"]:contains("ACCEPTED!") a[id$="source"]::attr("href")'
        ).getall()

        task_name_indexes = [i for i, x in enumerate(acc_submits) if x[0].isdigit()]
        indices = [(i + 1, j - 1) for i, j in zip(task_name_indexes, task_name_indexes[1:] + [len(acc_submits)])]

        task_names = [acc_submits[i] for i in task_name_indexes]
        last_submits = [(acc_submits[i:j + 1][:1] or [None])[0] for i, j in indices]

        for name, source_path in zip(task_names, last_submits):
            if source_path:
                yield scrapy.Request(
                    'http://fresh.nsuts.ru/nsuts-new/' + source_path,
                    callback=self.save_code,
                    cb_kwargs={'task_name': name, 'dir_path': dir_path}
                )

    @staticmethod
    def save_code(response, task_name, dir_path):
        path = os.path.join(dir_path, task_name.replace('.', '') + ".c")
        code = response.css('code::text').get()
        with open(path, 'w') as f:
            f.write(code)
