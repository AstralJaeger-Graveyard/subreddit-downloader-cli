import abc

from asyncpraw import Reddit
from asyncpraw.models import Submission


class BaseUrlResolver:
    """
        This class serves as BaseUrlResolver, the purpose is to allow a more generic and abstracted approach for
        different behaviours concearning for Reddit submissions types like url submissions
        , self-text submissions and crossposts
    """
    def __init__(self, reddit: Reddit):
        self.reddit = reddit

    @abc.abstractmethod
    def resolve(self, sumbission: Submission) -> set[str]:
        """
            This method defines the behaviour to resolve urls from a submission.
            Params:
                submission (Submission): The submission to inspect
            Returns:
                urls (set[str]): A set of urls from the submission
        """
        pass


class StandardUrlResolver(BaseUrlResolver):

    def __init__(self, reddit: Reddit):
        super().__init__(reddit)

    async def resolve(self, submission: Submission) -> set[str]:

        urls = set()
        if hasattr(submission, "media_metadata") and submission.media_metadata is not None:
            for key, image_item in enumerate(submission.media_metadata.values()):
                largest_image = image_item['s']
                keys = {'u', 'mp4', 'gif'}
                for k in keys:
                    if k in largest_image:
                        urls.add(largest_image[k])
                        break
        elif not submission.is_self and not hasattr(submission, "media_metadata") and "gallery" not in submission.url:
            urls.add(submission.url)
        return urls


class CrosspostUrlResolver(BaseUrlResolver):

    def __init__(self, reddit: Reddit):
        super().__init__(reddit)

    async def resolve(self, submission: Submission) -> set[str]:
        if hasattr(submission, "crosspost_parent") and submission.crosspost_parent is not None:
            max_retires = 10
            retries = 0
            while retries < max_retires:
                try:
                    return await StandardUrlResolver(self.reddit) \
                        .resolve(await self.reddit.submission(url = f"https://www.reddit.com{submission.permalink}"))
                except TimeoutError as timeout_error:
                    print(f"A TimeoutError occurred while resolving https://www.reddit.com{submission.permalink}: {timeout_error}")
                    retries += 1
                except Exception as error:
                    print(f"An Error occurred while resolving https://www.reddit.com{submission.permalink}: {error}")
                    return set()
        return set()
