var system = require('system');
if (system.args.length !== 2) {
    console.log('Usage: phantomjs phantom_downloader.js <URL>');
    phantom.exit(1);
}

var url = system.args[1],
    page = require('webpage').create();

var WAIT_TIME = 3000;

page.settings.userAgent = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36';

page.open(url, function(status) {
    if (status !== 'success') {
        console.log('Error opening page: ' + url);
        phantom.exit(1);
    } else {
        window.setTimeout(function() {
            console.log(page.content);
            phantom.exit();
        }, WAIT_TIME);
    }
});
