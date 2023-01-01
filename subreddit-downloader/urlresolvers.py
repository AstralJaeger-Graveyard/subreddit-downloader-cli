from asyncpraw.models import Submission


class BaseUrlResolver:

    def __int__(self):
        pass

    def resolve(self, sumbission: Submission) -> set[str]:
        pass


class StandardUrlResolver(BaseUrlResolver):

    def __int__(self):
        pass

    def resolve(self, submission: Submission) -> set[str]:

        urls = set()

        if hasattr(submission, "media_metadata"):
            image_dict = submission.media_metadata
            for image_item in image_dict.values():
                largest_image = image_item['s']
                if hasattr(largest_image, 'u'):
                    urls.add(largest_image['u'])
                elif hasattr(largest_image, 'mp4'):
                    urls.add(largest_image['mp4'])
                elif hasattr(largest_image, 'gif'):
                    urls.add(largest_image['gif'])

        if not submission.is_self and \
                not hasattr(submission, "media_metadata") and \
                "gallery" not in submission.url:
            if submission.url.startswith("/r/"):
                print(f"{' ' * 15} URL {submission.url} for submission {submission.permalink} is malformed")
                urls.add(f"https://www.reddit.com{submission.url}")
            else:
                urls.add(submission.url)
        return urls
