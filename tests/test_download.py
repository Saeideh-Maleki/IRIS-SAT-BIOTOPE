from download import month_products


class FakeReply:
    def raise_for_status(self):
        pass

    def json(self):
        return {'value': [
            {'Name': 'S2A_MSIL2A_20220801', 'Id': 'high',
             'Attributes': [{'Name': 'cloudCover', 'Value': 40}]},
            {'Name': 'S2A_MSIL2A_20220815', 'Id': 'low',
             'Attributes': [{'Name': 'cloudCover', 'Value': 8}]},
        ]}


class FakeSession:
    def get(self, url, params, timeout):
        assert '2022-08-01' in params['$filter']
        assert 'SENTINEL-2' in params['$filter']
        return FakeReply()


def test_catalogue_chooses_low_cloud_product():
    items = month_products(FakeSession(), [-1.23, 44.51, -1.16, 44.56], 2022, 8, 25)
    assert len(items) == 1
    assert items[0]['Id'] == 'low'
